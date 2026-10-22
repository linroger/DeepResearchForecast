# linear-1 — linear_research.py (v3 engine) part 1

Slice: `deerflow_bridge/linear_research.py` lines 1–3055 (the whole file is 6,379 lines; lines 3056–6379 — `KiqAgent`, `_Engine`, the phase methods, the factories and `run` — belong to the next slice and are cited here only to show how this slice is used). Studied on branch `main` at `c20ec60`; the file has no uncommitted changes (`git status --short` was empty).

Some claims below were checked by running pure functions offline. Those runs imported the module with `PYTHONDONTWRITEBYTECODE=1`; `research_gateway` imports only the standard library. They are marked **(probe)**. No LLM, network or backend was involved.

---

## Purpose & position in the pipeline

- Stage 1 of the DRF pipeline is deep research. The backend orchestrator starts `deerflow_research.py` as a child process. When `RESEARCH_ENGINE` resolves to `v3`, the bridge imports `linear_research` **by bare name** and calls `linear_research.run(question, out_dir, args, meta, plog, write_meta, bridge=...)` (`deerflow_bridge/deerflow_research.py:16516-16534`, dispatch at `deerflow_bridge/deerflow_research.py:16902-16903`). The orchestrator copies `linear_research.py` and `research_gateway.py` next to the deployed script, because the child runs with `sys.path[0]==deer-flow/` (`backend/app/services/pipeline_orchestrator.py:1352-1361`, `backend/app/services/pipeline_orchestrator.py:1530-1536`).
- The module docstring sets out the design: six strict phases, `plan → gather → gap → synthesize → qa → finalize`. Each phase persists its artifacts atomically under `out_dir/v3` before it is marked done, so a resume never pays for finished work twice (`deerflow_bridge/linear_research.py:16-38`, `deerflow_bridge/linear_research.py:98`). Every LLM call goes through `research_gateway`, using a cache-friendly layout `[ENGINE_CORE][RUN BRIEF][shared context…][task]` (`deerflow_bridge/linear_research.py:40-44`).
- **This slice contains no phase orchestration.** It holds the engine's *static and pure layer*:
  - the constants;
  - the one static system prompt `ENGINE_CORE`;
  - the localized defaults and prompt templates;
  - depth presets and env-knob resolution;
  - language detection;
  - durable run-state (`v3/state.json`) and work-dir identity;
  - the plan data model with its deterministic normalisation and fallbacks;
  - the RUN BRIEF renderer;
  - the canonical scenario block and a mirror of the backend scenario parser;
  - scenario-weight repair and lint;
  - citation normalisation;
  - research-notes parsing with number verification (VERIFIED / REPORTED / UNVERIFIED);
  - deterministic page-sentence extraction for fallback notes;
  - the evidence digest builder;
  - the writer-reply section splitter.
- Contract with the bridge, as stated in the docstring:
  - `run` never closes `plog`.
  - `run` never mutates `os.environ`, except for the lease cap described in `_bridge_lease`, which is outside this slice.
  - `run` never writes outside `out_dir`.
  - `run` always leaves `meta.status` terminal.
  - Exit code is 0 iff `research_report.md` (≥ 400 chars) was written, and 2 otherwise (resumable) (`deerflow_bridge/linear_research.py:46-53`).

---

## Walkthrough (source order)

### 1. Module header (1–93)

- **Docstring** (`deerflow_bridge/linear_research.py:1-54`). It explains why the file was rewritten:
  - The legacy LangGraph loop used 46.8M prompt tokens on one question.
  - The previous v2 file had these bugs:
    - `str.format` KeyErrors on templates containing JSON;
    - async-only tools called synchronously;
    - sections out of order;
    - References that dumped the whole ledger;
    - no `[usage]` lines;
    - os.environ mutation;
    - notes written *after* KIQs were marked done.

  The docstring also lists the six phases and the bridge contract.
- **Imports** (`deerflow_bridge/linear_research.py:56-81`): stdlib plus `import research_gateway as rg` (`deerflow_bridge/linear_research.py:81`). The gateway is a bare-name sibling import, with no package path.
- **`__all__`** (`deerflow_bridge/linear_research.py:83-93`): `ENGINE_CORE`, `ENGINE_VERSION`, `Preset`, `detect_language`, `parse_report_scenarios`, `postprocess_notes`, `render_scenario_block`, `resolve_preset`, `run`. Tests also reach many private names, for example `lr._PROMPT_TEMPLATES` at `backend/tests/test_research_engine_v3.py:423-424`.

### 2. Engine constants (95–218)

| Name | Value | Meaning / consumer | Anchor |
|---|---|---|---|
| `ENGINE_VERSION` | `"v3.0"` | Part of the run identity. A mismatch archives `v3/` | `deerflow_bridge/linear_research.py:95`, `deerflow_bridge/linear_research.py:986` |
| `WORK_DIRNAME` / `STATE_FILENAME` | `"v3"` / `"state.json"` | Work dir `out_dir/v3`, state file `v3/state.json` | `deerflow_bridge/linear_research.py:96-97` |
| `PHASES` | 6-tuple | Phase order; also read by the finalize code at 5893 and by a test (`backend/tests/test_research_engine_v3.py:781`) | `deerflow_bridge/linear_research.py:98` |
| `MIN_REPORT_CHARS` | 400 | Minimum report size for exit 0 (used at 5531-5533) | `deerflow_bridge/linear_research.py:100` |
| `RESERVE_SHARE` | 0.35 | Budget reserve share handed to the gateway factory (6273) | `deerflow_bridge/linear_research.py:101` |
| `SCOUT_QUERIES_MIN/MAX` | 4 / 6 | Scope prompt bounds; scout search cap | `deerflow_bridge/linear_research.py:102-103` |
| `SCOUT_DIGEST_CHARS` | 6000 | Cap on the scout-results digest (used in `_scout`, 4349-4361) | `deerflow_bridge/linear_research.py:104` |
| `SEED_QUERIES_PER_KIQ` / `SEED_ROWS_PER_KIQ` / `SEED_SNIPPET_CHARS` | 2 / 6 / 200 | Seed searches per KIQ, rows shown, snippet chars (4614, 4622) | `deerflow_bridge/linear_research.py:105-107` |
| `AGENT_CONTEXT_TOKEN_CAP` | 60,000 | Agent conversation cap (3622) | `deerflow_bridge/linear_research.py:108` |
| `NOVELTY_PATIENCE` | 2 | Steps without a new source before an agent stops (3542) | `deerflow_bridge/linear_research.py:109` |
| `MAX_TOOL_CALLS_PER_STEP` | 3 | Parallel tool calls per step; extra calls get `TOOL_CALLS_SKIPPED_TEXT` | `deerflow_bridge/linear_research.py:110-113` |
| `MAX_STORED_READS_PER_AGENT` / `READ_DUPLICATE_JACCARD` | 6 / 0.65 | Free re-reads from the page store; near-duplicate focus is refused (`_repeats_read`, 3395-3400) | `deerflow_bridge/linear_research.py:114-122` |
| `FINAL_NOTES_GRACE_S` / `FINAL_NOTES_GRACE_SHARE` | 90 s / 0.25 | Time held back for the forced final-notes call (4514-4521) | `deerflow_bridge/linear_research.py:123-128` |
| `SECTION_MIN_CHARS`, `WRITER_BODY_MIN_CHARS`, `LEAD_CHARS`, `EXCERPT_CHARS` | 200, 80, 700, 1200 | Writer/QA sizes | `deerflow_bridge/linear_research.py:129-132` |
| `MAX_REPAIRS`, `MAX_CRITIQUE_ISSUES`, `MAX_CRITIQUE_REWRITES` | 3, 5, 3 | QA repair / critique bounds | `deerflow_bridge/linear_research.py:133-135` |
| `CITATION_KEEP_RATIO` | 0.8 | QA citation-retention threshold (5380) | `deerflow_bridge/linear_research.py:136` |
| `GAP_MIN_NEW_VERIFIED`, `GAP_DUPLICATE_JACCARD` | 3, 0.6 | Gap-round novelty rules (4730, 4755) | `deerflow_bridge/linear_research.py:137-138` |
| `GAP_PROVIDER_STOP` | `"provider failure"` | Stop reason that leaves the gap phase "partial" | `deerflow_bridge/linear_research.py:139-141` |
| `GAP_MIN_SEARCHES_PER_FOLLOWUP` / `GAP_MIN_FETCHES_PER_FOLLOWUP` | 3 / 1 | Minimum tool budget per follow-up (4678) | `deerflow_bridge/linear_research.py:142-146` |
| `WRITER_/EXTRACT_/AGENT_RETRY_MAX_TOKENS` | 32k / 64k / 12k | Ceilings for the single 2× retry when a reply hits `finish_reason=length` | `deerflow_bridge/linear_research.py:147-153` |
| `TRUNCATION_RETRY_MIN_SECONDS` | 120 | Deadline time a truncation retry needs | `deerflow_bridge/linear_research.py:154` |
| `DEFAULT_EXTRACT_MAX_TOKENS` | 32,000 | Default of the `max_tokens_extract` knob | `deerflow_bridge/linear_research.py:155-159` |
| `REPLAN_MIN_REMAINING_SHARE` | 0.75 | Outage re-plan only if ≥ 75% of the time budget remains | `deerflow_bridge/linear_research.py:160-163` |
| `DEFAULT_ACTOR_CAST` / `ACTOR_PROMPT_CEILING` | 20 / 60 | Cast cap default; number named in prompts when the cap is disabled | `deerflow_bridge/linear_research.py:164-169` |
| `MAX_TIMELINE_ROWS` / `MAX_QUANT_ROWS` / `MAX_CONTESTED_ROWS` | 40 / 60 / 15 | Fact-extraction row caps | `deerflow_bridge/linear_research.py:170-172` |
| `DEFAULT_STALE_DAYS` | 365 | Staleness horizon used in finalize (5749) | `deerflow_bridge/linear_research.py:173` |
| `PHASE_TIME_SHARE` | plan .12, gather .55, gap .3, synthesize .75, qa .6 | Each phase's wall clock as a fraction of the run time *left when the phase starts*; finalize has none (consumed in `_Engine.phase`, 4140) | `deerflow_bridge/linear_research.py:174-178` |
| `ENGLISH` / `CHINESE` | `"English"` / `"Chinese"` | Language tokens | `deerflow_bridge/linear_research.py:180-181` |
| `AGENT_TOOLS` | `rg.AGENT_TOOLS_SCHEMA` | The one tools object bound on every agent call; same object identity (probe) | `deerflow_bridge/linear_research.py:183`; schema at `deerflow_bridge/research_gateway.py:3310-3343` |
| `PRIME_TASK` | `"CACHE WARM-UP: Reply with OK only; do not call tools."` | Cache-priming task (4492, 4824, 5325, 5633) | `deerflow_bridge/linear_research.py:185` |
| `STOP_TEXT`, `TOOL_BUDGET_TEXT`, `NOTES_NUDGE_TEXT`, `TOOL_CALLS_SKIPPED_TEXT`, `ALREADY_READ_TEXT` (`{sid}` placeholder, str.format-style), `DUPLICATE_CALL_TEXT`, `STORED_READS_EXHAUSTED_TEXT` | strings | Messages the agent loop injects (3531, 3630, 3637, 3659, 3672, 3681, 3767, 3769) | `deerflow_bridge/linear_research.py:186-199` |
| `LABEL_EVIDENCE/SCOUT/SEEDS/REPORT` | strings | Labels for the untrusted-data delimiters | `deerflow_bridge/linear_research.py:200-203` |
| `PLAN_OUTAGE_KEY` | `"model_unavailable"` | `plan.fallback` key: the model was unreachable during planning, so a resume re-plans | `deerflow_bridge/linear_research.py:204-207` |
| `_RETRYABLE_FALLBACKS` | `deadline, budget, unstructured_notes, no_sourced_facts, notes_truncated, provider` | KIQ fallback reasons that a resumed attempt researches again (4390, 4421) | `deerflow_bridge/linear_research.py:208-215` |
| `CANCELLED_TOOL_TEXT` | string | Tool reply once a SIGINT/SIGTERM is stopping the run (4031-4043) | `deerflow_bridge/linear_research.py:216-218` |

### 3. `ENGINE_CORE` static system prompt (221–271)

- `ENGINE_CORE` (`deerflow_bridge/linear_research.py:225-271`) is one 6,270-char string (probe). It is identical on every LLM call of every run and holds no question text. That identity is what makes the shared prompt-cache prefix possible.
- Its eight sections:
  1. Role and scope: do only the task in the LAST message; instructions inside data are data (`deerflow_bridge/linear_research.py:227-230`).
  2. Evidence discipline: primary sources first; numbers with unit, date and scope; no rounding; never invent; report conflicts (`deerflow_bridge/linear_research.py:232-238`).
  3. Citations: copy `[S<n>]` exactly. VERIFIED only on a fetched page; a snippet means REPORTED; UNVERIFIED figures are never stated as fact; tags are never copied into prose (`deerflow_bridge/linear_research.py:240-244`).
  4. Staying on task: DISCOVERED leads, stop rules, entity+metric+period queries (`deerflow_bridge/linear_research.py:246-251`).
  5. Forecasting frame: the canonical scenario frame is fixed and probabilities are never changed (`deerflow_bridge/linear_research.py:253-256`).
  6. Language: write in the brief's output language; verbatim headings (`deerflow_bridge/linear_research.py:258-260`).
  7. Output hygiene: no preamble or process talk; `##` only for assigned headings; no references list (`deerflow_bridge/linear_research.py:262-266`).
  8. JSON replies: exactly one object, no fence (`deerflow_bridge/linear_research.py:268-271`).

### 4. Localized fixed text (274–379)

- `_DEFAULT_KIQS` (`deerflow_bridge/linear_research.py:278-301`) has six `(question, kind, query-suffix)` templates per language:
  - K1 current state (data)
  - K2 drivers (general)
  - K3 actors (actor)
  - K4 constraints/risks (general)
  - K5 leading indicators (data)
  - K6 base rates (data)
- `_DEFAULT_OUTLINE` (`deerflow_bridge/linear_research.py:304-325`) has eight default sections with their 1-based default KIQ numbers and a focus:
  - Background (K1)
  - Drivers (K2)
  - Actors (K3)
  - Constraints (K4)
  - Base Rates (K6)
  - Leading Indicators (K5)
  - Scenarios and Probabilities (K2, K4, K5, K6)
  - Implications (none)

  None of these sections is flagged as the scenario section. `_ensure_scenario_section` picks it later by title score.
- `_EXTRA_OUTLINE` (`deerflow_bridge/linear_research.py:327-334`) has eight filler titles per language for padding below `sections_min`.
- `_DEFAULT_FRAME` (`deerflow_bridge/linear_research.py:336-347`) is Base 50 / Upside 25 / Downside 25 (EN), or 基准/上行/下行情景 (ZH).
- `_TEXT` (`deerflow_bridge/linear_research.py:349-370`) has eight UI strings per language: `exec_title`, `scenario_title`, `scenario_block`, `no_evidence`, `incomplete`, `nothing_read`, `frame_line`, `no_findings`.
- `_lang_key(language)` (`deerflow_bridge/linear_research.py:373-375`) returns `CHINESE` only for the exact string `"Chinese"`; every other language uses the English tables. `_text(language, key)` (`deerflow_bridge/linear_research.py:378-379`) looks up `_TEXT`.

### 5. Prompt templates (382–522)

- All templates are `string.Template` (`$name`), because they contain literal JSON braces. The header comment says no template may contain a literal `$` (`deerflow_bridge/linear_research.py:382-385`). Every registered template reports `is_valid()==True` (probe).

| Template | Placeholders (probe) | Rendered at | Anchor |
|---|---|---|---|
| `_T_PRE_BRIEF` "RUN BRIEF (planning stage)" | question, language, as_of | `render_pre_brief` (1511) | `deerflow_bridge/linear_research.py:388-391` |
| `_T_SCOPE` | language, min_queries, max_queries | `_plan_calls` 4322 | `deerflow_bridge/linear_research.py:393-401` |
| `_T_PLAN` | min_kiqs, max_kiqs, min_sections, max_sections, language, actor_cap | 4333 | `deerflow_bridge/linear_research.py:403-414` |
| `_T_KIQ_TASK` | kiq_id, question, why, emphasis, seeds, max_searches, max_fetches, max_steps, language | 4628-4631 | `deerflow_bridge/linear_research.py:416-433` |
| `_T_GAP` | round, coverage, already, max_followups, language | 4737 | `deerflow_bridge/linear_research.py:435-443` |
| `_T_EXEC` | heading, length, language | 5142 | `deerflow_bridge/linear_research.py:445-449` |
| `_T_CRITIQUE` | max_issues, language | 5390 | `deerflow_bridge/linear_research.py:451-455` |
| `_T_ACTORS` | actor_cap, language | 5626 | `deerflow_bridge/linear_research.py:457-468` |
| `_T_FACTS` | max_events, max_quant, max_contested, language | 5628 | `deerflow_bridge/linear_research.py:470-480` |

- **The plan JSON contract** (`_T_PLAN`, `deerflow_bridge/linear_research.py:406-414`) has four parts:
  - `kiqs[{question, queries[2-3], kind∈data|actor|general}]`;
  - `sections[{title, kiqs[1-based], focus, scenario:true on exactly one}]`, with no exec summary, intro, conclusion or references;
  - `scenarios[{name 2-5 words without %, weight int summing to 100, thesis}]`, 2–6 of them;
  - `actors[{name, type∈Person|Organization|Government|Media|Platform|Other, why}]`, at most `$actor_cap`.
- **The notes format** that agents must return (`_T_KIQ_TASK`, `deerflow_bridge/linear_research.py:424-433`) uses four English headings — `## Findings`, `## Conflicts`, `## Open questions`, `## Discovered`. Bullets are `- <fact> [S<n>] (VERIFIED|REPORTED)`, written in the output language, with 6–15 findings expected. The tools are described as `web_search(query)` and `web_fetch(url, focus)`; `web_fetch` also accepts a marker such as `S12` in place of a URL (`deerflow_bridge/linear_research.py:423`).
- `_T_ACTORS` (`deerflow_bridge/linear_research.py:457-468`) asks for the full actor schema: central_question, as_of_date, situation_brief, and actors with incentives, worldview, salience and simulation_tier 1-4. The relationship types are an enum of 16; valence, polarity and strength are also requested.
- `_T_FACTS` (`deerflow_bridge/linear_research.py:470-480`) asks for `key_events`, `quantitative_facts` (value_type actual|estimate|forecast|target, `source_ref` = the S-marker) and `contested_claims`.
- `_PROMPT_TEMPLATES` registry (`deerflow_bridge/linear_research.py:482-492`): see Surprises.
- `_SECTION_RULES` (`deerflow_bridge/linear_research.py:494-503`) holds the writer rules: cite only SOURCE INDEX markers, prefer sources marked fetched, handle tags, use `###` for sub-headings, no process narration. It is used at 4939.
- `_SCENARIO_SECTION_NOTE` (`deerflow_bridge/linear_research.py:505-509`) tells the writer the engine inserts the canonical probability list and that it must not write its own. It is used at 4938.
- `_KIND_EMPHASIS` (`deerflow_bridge/linear_research.py:511-517`) gives one emphasis sentence per KIQ kind. It is used at 4631.
- `_render(template, **fields)` (`deerflow_bridge/linear_research.py:520-522`) stringifies every value and calls `substitute`. A missing field raises KeyError on purpose (a caller bug).

### 6. Small pure helpers (525–606)

- `_iso_now`, `_utc_date`, `_compact_utc` (`deerflow_bridge/linear_research.py:529-538`) return UTC timestamps. The compact form `%Y%m%dT%H%M%SZ` names stale-dir archives.
- `_sha256(text)` (`deerflow_bridge/linear_research.py:541-542`) is used for the identity `question_sha256` (3970).
- `_collapse(value, limit=0)` (`deerflow_bridge/linear_research.py:545-554`) collapses whitespace to one line. When a limit is set, it cuts to `limit-1` chars, backs up to a space if that space is past 60% of the limit, strips `,;:` and appends `…`.
- `_norm_key` (`deerflow_bridge/linear_research.py:557-560`) is the dedup key: NFKC, casefold, and only `\w` minus `_` kept (CJK included).
- `_name_key` (`deerflow_bridge/linear_research.py:563-566`) is a byte-for-byte mirror of backend `normalize_name` (`backend/app/utils/actors.py:145-156`). It is used for scenario and actor identity.
- `_natural_key(kid)` (`deerflow_bridge/linear_research.py:569-572`) orders K-ids before G-ids, numerically: `K2 < K10 < G1F1 < G1F2 < G2F1` (probe).
- `_as_str_list(value, limit, item_chars=300)` (`deerflow_bridge/linear_research.py:575-592`) accepts a str or list. It skips nested or None items, collapses and caps each item, dedups by `_norm_key`, and stops at `limit`.
- `_read_json` / `_read_text` (`deerflow_bridge/linear_research.py:595-606`) return `None` on OSError or ValueError and never raise.

### 7. Depth presets and knob resolution (609–762)

- `_DEPTH_PRESETS` (`deerflow_bridge/linear_research.py:615-631`):

| knob | quick | standard | deep |
|---|---|---|---|
| max_kiqs | 4 | 7 | 10 |
| agent_max_steps | 5 | 7 | 9 |
| searches_per_kiq / fetches_per_kiq | 3/3 | 4/4 | 5/6 |
| max_searches_total / max_fetches_total | 30/24 | 70/50 | 140/110 |
| gap_rounds × followups_per_round | 0×0 | 1×3 | 2×4 |
| sections_min–max | 6–8 | 8–12 | 11–16 |
| target_units | 3000 | 6000 | 11000 |
| critique | False | False | True |
| budget_units | 1.2M | 2.5M | 5.0M |
| time_budget_s | 1200 | 2700 | 5400 |
| workers | 4 | 4 | 4 |
| digest_cap | 30k | 60k | 90k |
| max_tokens_extract | 32k | 32k | 32k |

- `_KNOB_BOUNDS` (`deerflow_bridge/linear_research.py:634-641`) clamps each knob. Examples: max_kiqs 1–24, workers 1–16, time_budget_s 60–604800, digest_cap 5k–400k, max_tokens_extract 1024–128k.
- `_TRUTHY`/`_FALSY` (`deerflow_bridge/linear_research.py:643-644`).
- `@dataclass(frozen=True) Preset` (`deerflow_bridge/linear_research.py:647-669`) holds the 17 knobs plus `depth` and `notes` (diagnostics that the engine logs once).
- `_parse_knob(raw, default)` (`deerflow_bridge/linear_research.py:672-686`):
  - A bool default accepts only truthy or falsy words; anything else returns None.
  - Numbers parse through `float`. Non-finite values return None. If the default is an int, the result is `int()`-truncated (so "4.9" becomes 4).
- `scheduled_tool_calls(values)` (`deerflow_bridge/linear_research.py:689-695`) computes the worst-case run totals:
  - `investigations = max_kiqs + gap_rounds*followups_per_round`
  - `searches = SCOUT_QUERIES_MAX + (SEED_QUERIES_PER_KIQ + searches_per_kiq) * investigations`
  - `fetches = fetches_per_kiq * investigations`

  This gives quick 26/12, standard 66/40 and deep 132/108 (`deerflow_bridge/linear_research.py:613-614`; probe).
- `resolve_preset(depth, env=None)` (`deerflow_bridge/linear_research.py:698-762`):
  1. `env` defaults to `os.environ` (`deerflow_bridge/linear_research.py:711`).
  2. An empty depth means `standard`. An unknown depth falls back to standard and adds a note (`deerflow_bridge/linear_research.py:713-716`).
  3. For each knob, `RESEARCH_LINEAR_<KNOB>` is read when non-blank. An unparsable value is noted and the preset value kept. An out-of-range value is clamped and noted. Every applied value is recorded as *explicit* (`deerflow_bridge/linear_research.py:719-734`).
  4. If `sections_min > sections_max`, `sections_min` is set to `sections_max` (`deerflow_bridge/linear_research.py:735-738`).
  5. The run totals are raised to `scheduled_tool_calls` unless they were set explicitly. An explicit total below the schedule is kept and noted, and gap rounds are later trimmed (`deerflow_bridge/linear_research.py:739-747`).
  6. `workers = min(workers, RESEARCH_MODEL_CONCURRENCY_GLOBAL)` when that value is an int ≥ 1; otherwise a note is added (`deerflow_bridge/linear_research.py:748-754`).
  7. `time_budget_s = min(time_budget_s, 0.85 × DEERFLOW_RESEARCH_TIMEOUT)` when that value is > 0 (`deerflow_bridge/linear_research.py:755-761`).
  8. Returns `Preset(depth=key, notes=tuple(notes), **values)` (`deerflow_bridge/linear_research.py:762`).
- Example (probe): `quick` with `RESEARCH_LINEAR_MAX_KIQS=10` raises the totals to 56/30 with no note.

### 8. Language (765–803)

- Regexes (`deerflow_bridge/linear_research.py:769-775`):
  - Han, Kana, Hangul and combined-CJK character classes;
  - `_CHINESE_ALIASES`: chinese, zh, zh-cn, zh_cn, zh-hans, zh-tw, zh-hant, cn, 中文, …, mandarin;
  - `_ENGLISH_ALIASES`.
- `detect_language(question, target_language=None)` (`deerflow_bridge/linear_research.py:778-803`):
  - An explicit `target_language` wins:
    - Chinese if it is an alias or contains "chinese";
    - English if it is an English alias;
    - **otherwise the explicit string is returned verbatim** (`deerflow_bridge/linear_research.py:792`).
  - Otherwise the question is classified by its share of CJK characters:
    - fewer than 20% of non-space chars → English;
    - any kana → `"Japanese"`;
    - any hangul → `"Korean"`;
    - otherwise → Chinese.
  - An empty question → English.
- Probes:
  - a Chinese question → Chinese;
  - `日本の…` → Japanese;
  - `"zh-Hans-CN"` → `"zh-Hans-CN"`;
  - `"Simplified Chinese"` → Chinese;
  - `"French"` → `"French"`.
- Called at `_Engine.__init__` with `args.target_language` (3961).

### 9. `_Reporter` (806–827)

- `_Reporter` (`deerflow_bridge/linear_research.py:810-827`) wraps the bridge `ProgressLog`. It exposes only `write(kind, message)`. With `plog=None` it is a no-op, and every exception is swallowed (`deerflow_bridge/linear_research.py:821-827`). It is deliberately unable to close the log, which `deerflow_research.main` owns. [verifier: the actual close is the bridge's `_dispatch_v3_engine` `finally: plog.close()`, which `main` calls; the engine itself never closes it (deerflow_bridge/deerflow_research.py:16560-16561, deerflow_bridge/deerflow_research.py:16902-16903)]

### 10. Durable run state (830–995)

- `_EngineFailure(Exception)` (`deerflow_bridge/linear_research.py:834-835`) is a handled, resumable failure. `_Engine.run` turns it into `meta.status="failed"`, `meta.error=str(exc)`, and exit 2 (`deerflow_bridge/linear_research.py:4197-4200`).
- `RunTerminated(SystemExit)` (`deerflow_bridge/linear_research.py:838-843`) carries exit code `128+SIGTERM` = 143. It is raised at 6291, 6312 and 6361. [verifier: it is raised only at 6312 (`on_sigterm`); 6291 is a docstring mention and 6361 is the `isinstance` check that records `meta.error="terminated"` before re-raising. The handler is installed only in the main thread and only when SIGTERM's previous disposition is SIG_DFL (deerflow_bridge/linear_research.py:6296-6317, deerflow_bridge/linear_research.py:6358-6364)] Because it subclasses `SystemExit`, the bridge's `except Exception` does not catch it; the `BaseException` branch records it and re-raises (`deerflow_bridge/deerflow_research.py:16542-16551`).
- `_CallTally` (`deerflow_bridge/linear_research.py:846-885`):
  - It keeps thread-safe counts of `served`, `refused`, `budget` and `failed`.
  - `watch(invoke)` wraps `ModelGateway.invoke`. The order of the except clauses matters: `rg.ContentFiltered` → refused, `rg.BudgetExhausted` → budget, any other `rg.GatewayError` → failed, success → served. Errors are re-raised unchanged, and non-gateway exceptions are not counted (`deerflow_bridge/linear_research.py:868-885`).
  - It is installed at 3995-3996. Cache primes do not go through `invoke` (`deerflow_bridge/research_gateway.py:1921-1966`), so they are not counted, as the docstring says (`deerflow_bridge/linear_research.py:847-848`).
- `_RunState` (`deerflow_bridge/linear_research.py:888-960`) represents `v3/state.json`:
  - `__init__(path, data, writer)` stores an **RLock**. Mutators hold it across the write, so an older snapshot can never overwrite a newer one when KIQs finish concurrently (`deerflow_bridge/linear_research.py:895-901`).
  - `fresh(path, identity, writer)` writes `{"engine_version","identity","created_at","phases":{},"kiqs":{}}` immediately (`deerflow_bridge/linear_research.py:903-910`).
  - `save()` writes `json.dumps(..., ensure_ascii=False, indent=2)` through the injected writer. In production that writer is `_Engine._write_internal`, which calls `rg._atomic_write_text`: temp file in the same dir, fsync, `os.replace` (`deerflow_bridge/linear_research.py:4054-4055`, `deerflow_bridge/research_gateway.py:2340-2355`).
  - `phase(name)` returns a copy; `is_done(name)` checks `status=="done"` (`deerflow_bridge/linear_research.py:916-921`).
  - `set_phase(name, status, detail)` (`deerflow_bridge/linear_research.py:923-933`): `running` sets `started_at` and drops `finished_at`; any other status sets `finished_at`. Detail is capped at 500 chars, and the state is saved.
  - `reset_phases(names)` returns the names that had a status (`deerflow_bridge/linear_research.py:935-941`).
  - `kiq(kid)`, `reset_kiqs()` (forget every KIQ), and `mark_kiq(kid, **info)` (adds `finished_at`, saves) (`deerflow_bridge/linear_research.py:943-956`).
  - `snapshot()` returns a deep copy via a JSON round-trip (`deerflow_bridge/linear_research.py:958-960`).
- `_unique_stale_path(out_dir)` (`deerflow_bridge/linear_research.py:963-970`) returns `out_dir/v3.stale-<YYYYMMDDTHHMMSSZ>`, adding `-1`, `-2`, … on collision.
- `_open_work_dir(out_dir, identity, writer, reporter)` (`deerflow_bridge/linear_research.py:973-995`) reuses `v3/` only if `state.json` parses to a dict whose `engine_version == ENGINE_VERSION`, whose `identity` equals the new identity exactly, and whose `phases` and `kiqs` are dicts. Otherwise it **renames** `v3/` to the stale path, logs a warn, recreates `v3/`, and starts fresh state. It returns `(work, state, resumed)`.
  - The identity (built at 3969-3971 [verifier: the dict literal is at 3970-3972; 3969 is `self._page_numbers` (deerflow_bridge/linear_research.py:3970-3972)]) is `{question_sha256 (whitespace-collapsed question), depth, model, language, engine_version}`.

### 11. Plan model and deterministic normalisation (998–1540)

**Regexes and constants** (`deerflow_bridge/linear_research.py:1002-1037`):
- `_KIQ_KINDS` = general, actor, data.
- `_ACTOR_TYPES` maps synonyms such as agency or regulator to Government, and company or firm to Organization.
- `_KIQ_ID_RE` = `^(?:K\d+|G\d+F\d+)$`.
- `_SCENARIO_CUE_RE` (scenario|情景|情境|场景) is the backend heading cue.
- `_FORECAST_SCENARIO_RE` excludes 场景.
- `_SCENARIO_PROBABILITY_RE` and `_USE_CASE_TITLE_RE`.
- `_NON_BODY_TITLES` (exec-summary and references titles, EN and ZH).
- `_TITLE_NUMBERING_RE` strips only a *leading enumerator*. It handles forms such as "1.", "2)", "1.2.", "(4)", "（一）", "一、", "IV.", "§3", "Section 2:", "Part II -" and "第三章". It never strips "5G", "2030 Outlook" or "2030年" (probe: "2030 Outlook" and "5G Rollout" are kept; "第三章 背景" becomes "背景").

**Dataclasses:**
- `Kiq{id, question, queries, kind="general", why="", round=0}` (`deerflow_bridge/linear_research.py:1040-1064`). `from_dict` rejects ids that do not match `_KIQ_ID_RE` and empty questions; it keeps at most 3 queries, coerces kind, and caps `why` at 400 chars.
- `OutlineSection{index, title, kiq_ids, focus, is_scenario}` (`deerflow_bridge/linear_research.py:1067-1077`).
- `Scenario{name, weight:int, thesis}` (`deerflow_bridge/linear_research.py:1080-1087`).
- `Plan` (`deerflow_bridge/linear_research.py:1090-1145`):
  - Fields: question, language, as_of, restated_question, horizon, kiqs, sections, scenarios, actors, key_entities, scout_queries, fallback dict.
  - `to_dict` is the persisted schema.
  - `from_dict` is the resume reload. It returns **None (re-plan) unless all of these hold**: KIQs non-empty with unique ids, sections non-empty, exactly one `is_scenario`, 2–6 scenarios with weights summing to 100 and each ≥ 1 with a name, and both question and as_of present (`deerflow_bridge/linear_research.py:1131-1137`). Section indexes are renumbered 1..n on reload (`deerflow_bridge/linear_research.py:1125-1128`).

**Functions:**
- `_short_query_base(question, language)` (`deerflow_bridge/linear_research.py:1148-1153`): Chinese uses the first 40 chars of the collapsed question. Other languages use up to 8 `rg.query_terms` (non-stopword terms of ≥ 3 chars), or else the first 120 chars.
- `fallback_kiqs(question, language, max_kiqs)` (`deerflow_bridge/linear_research.py:1156-1163`) takes the first `max_kiqs` localized templates. Each gets id `K<i>` and one query `"<base> <suffix>"` capped at `rg.MAX_QUERY_CHARS` (300, `deerflow_bridge/research_gateway.py:3349`).
- `_normalize_kiqs(raw, max_kiqs)` (`deerflow_bridge/linear_research.py:1166-1193`):
  - Accepts strings or dicts, reading `question`, `kiq` or `text`, capped at 400 chars.
  - Deduplicates by `_norm_key`; duplicates map to the first id.
  - Stops creating ids after `max_kiqs`.
  - Ids are **engine-assigned** K1..Kn, and LLM-supplied ids are ignored.
  - Queries are capped at 3 and 300 chars; with none, the question's first 200 chars are used.
  - Returns `(kiqs, index_map raw-position→id)`.
- `_strip_title_numbering` and `_section_title_key` (`deerflow_bridge/linear_research.py:1196-1204`): the title key is `_norm_key` of the title without markdown and numbering.
- `_resolve_kiq_refs(refs, index_map, n_raw, valid_ids)` (`deerflow_bridge/linear_research.py:1207-1229`):
  - Integers are 1-based, except that the list is treated as **0-based if the minimum int is 0**.
  - Strings `"K3"` or `"3"` are always read as 1-based raw positions.
  - Booleans are skipped, and the output is deduplicated.
  - So `"K3"` means "the LLM's 3rd KIQ", which may become engine id K2 if an earlier raw item was a duplicate (probe).
- `_normalize_sections(raw, …)` (`deerflow_bridge/linear_research.py:1232-1253`):
  - Accepts strings or dicts.
  - Title is cleaned of `#*_:` and numbering, then capped at 120 chars.
  - Duplicates and `_NON_BODY_TITLES` are dropped.
  - `is_scenario` is true for `True`, "true", "yes" or "1".
  - Focus is capped at 300 chars.
- `_default_sections(language, kiq_ids)` (`deerflow_bridge/linear_research.py:1256-1262`) builds the eight default sections, keeping only KIQ refs that exist.
- `_scenario_title_score(title)` (`deerflow_bridge/linear_research.py:1265-1277`):
  - 2 = a scenario word plus a probability word;
  - 1 = a scenario word only;
  - 0 = use-case titles without a probability word ("Deployment Scenarios and Use Cases", "应用场景");
  - "场景" counts only together with a probability word. Probe: "场景概率" scores 2.
- `_ensure_scenario_section(sections, language)` (`deerflow_bridge/linear_research.py:1280-1299`) leaves exactly one scenario section:
  - Among planner-designated sections, the best score wins, and on a tie the last one.
  - Otherwise the best-scoring title wins if its score is > 0.
  - Otherwise a default `_TEXT.scenario_title` section is inserted before the last section.
- `_clamp_sections(sections, language, smin, smax)` (`deerflow_bridge/linear_research.py:1302-1333`):
  - Above `smax`, it repeatedly pops the non-scenario section with the fewest KIQ ids, then the shortest focus, then the latest position. Its KIQ ids and focus (capped at 400) merge into the previous section, or into the new first section if index 0 was popped.
  - Below `smin`, it inserts titles from default outline + extra outline before the scenario section. It skips scenario-cue titles and titles whose key is a substring of, or contains, an existing key.
  - Finally it renumbers `index` 1..n.
- `_PERCENT_FRAGMENT_RE`, `_EMPTY_PROB_PARENS_RE`, and `_clean_scenario_name(name)` (`deerflow_bridge/linear_research.py:1336-1347`): the cleaner removes `[S#]`, markdown chars, `NN%` and empty "(probability)" parentheses, trims punctuation, and caps the name at 60 chars. Probe: `"**Base (50%)**"` becomes `"Base"`.
- `_parse_weight(value)` (`deerflow_bridge/linear_research.py:1350-1361`) returns `(number, explicit_percent)`. A bool or None gives `(None, False)`, and the first number in a string is used.
- `largest_remainder(values, total=100)` (`deerflow_bridge/linear_research.py:1364-1380`) gives integer shares that sum to `total`, with each share ≥ 1 (the largest share donates when needed). It raises ValueError if the values are not positive or there are more than `total` of them. [verifier: it raises only when the list is empty, no value is positive (sum <= 0) or len > total; an individual zero or negative value is clamped to 0 and still ends with a share >= 1 through donation (deerflow_bridge/linear_research.py:1366-1379)] Probes: `[1,1,1]` gives 34/33/33; `[99,0.01]` gives 99/1.
- `default_scenarios(language)` (`deerflow_bridge/linear_research.py:1383-1384`).
- `normalize_scenarios(raw, language)` (`deerflow_bridge/linear_research.py:1387-1422`):
  - Dedups names by `_name_key`, reading `name` or `scenario` for the name and `weight` or `probability` for the weight.
  - Thesis is taken from `thesis` or `narrative`, stripped of `**`, and capped at 280 chars.
  - **Fraction mode:** if every plain (non-`%`) weight is in (0, 1], the plain weights are multiplied by 100.
  - Items with no weight or a weight ≤ 0 are dropped. If more than 6 remain, the top 6 by weight are kept.
  - Fewer than 2 items gives `(default frame, True)`. Otherwise `largest_remainder` produces the shares and the result is `(frame, False)`.
- `actor_cast_max(env)` (`deerflow_bridge/linear_research.py:1425-1438`) mirrors `deerflow_research._actor_cast_max` (`deerflow_bridge/deerflow_research.py:2299-2312`):
  - unset, blank or not an int → 20;
  - ≤ 0 → 0 (the cap is disabled);
  - any other value is kept unclamped.

  It is used by `_Engine._actor_cap` (4132-4134). When the cap is 0, the prompt cap becomes `ACTOR_PROMPT_CEILING` = 60 (3962-3963).
- `_normalize_plan_actors(raw, cap)` (`deerflow_bridge/linear_research.py:1441-1459`) dedups by `_name_key` and caps names at 120 chars. Type is mapped via `_ACTOR_TYPES`, defaulting to "Other". `why` is taken from `why` or `role` and capped at 200 chars. Processing stops at `cap` when cap > 0.
- **`build_plan(question, language, as_of, preset, actor_cap, scope, raw_plan)`** (`deerflow_bridge/linear_research.py:1462-1508`) can never fail:
  1. Seeds the fallback flags `scope` and `plan`, which are set when either input is empty.
  2. Normalises the KIQs. If there are fewer than `min(2, max_kiqs)`, it marks `fallback.kiqs` and appends template KIQs not already present until `min(6, max_kiqs)` (`deerflow_bridge/linear_research.py:1472-1481`).
  3. Normalises the sections; if none remain, it marks `fallback.sections` and uses the defaults.
  4. Runs `_ensure_scenario_section`, then `_clamp_sections(preset.sections_min, preset.sections_max)`.
  5. Runs `normalize_scenarios`, setting `fallback.scenarios` when the default frame was used.
  6. Sets each KIQ's `why` to `"Feeds report sections: §i Title (focus); …"` (capped at 400), or to "Background evidence for the whole report." if no section uses it. It sets `fallback.unrouted_kiqs` if any KIQ is unrouted (`deerflow_bridge/linear_research.py:1491-1500`).
  7. Takes scout queries from scope (≤ 6, 300 chars each), restated_question (400) and horizon (120). Takes key_entities (≤ 12, 120 chars each). Records only the true fallback flags. [verifier: not every repair gets a flag: a default scenario section inserted by `_ensure_scenario_section` and sections merged or padded by `_clamp_sections` set no `plan.fallback` key (probe: planner sections "1. Intro" + "Market" with no scenario section gave fallback `{}` while "Scenarios and Probabilities" and three padding sections were added) (deerflow_bridge/linear_research.py:1487-1488, deerflow_bridge/linear_research.py:1508)]
- Probe, `build_plan(…, scope=None, raw_plan=None)` with quick:
  - fallback = scope, plan, kiqs, sections and scenarios;
  - KIQs K1–K4 only;
  - 8 sections, with "Scenarios and Probabilities" as the scenario section;
  - "Historical Base Rates" and "Leading Indicators" left without KIQs.
- `render_pre_brief` (`deerflow_bridge/linear_research.py:1511-1512`) renders `_T_PRE_BRIEF` with the collapsed question.
- **`render_brief(plan)`** (`deerflow_bridge/linear_research.py:1515-1540`) builds the RUN BRIEF once after planning; it is persisted as `v3/brief.md` (4226) and reused byte-identically. It contains:
  - the question, language, as-of and horizon ("not stated in the question" if empty);
  - a "Working formulation" line only when the restated question differs by `_norm_key`;
  - the KIQ list (plan KIQs only);
  - the outline with an exec-summary placeholder, `§i Title` lines and a References placeholder;
  - the canonical frame as `- name — NN% — thesis`;
  - "Actors to track" and "Key entities" when present.

### 12. Canonical scenario block and backend-parser mirror (1543–1909)

- Mirror regexes (`deerflow_bridge/linear_research.py:1551-1559`): `_SCN_AGGREGATE_RE`, `_MD_HEADING_RE` (`##`–`######`), `_MD_BOLD_ITEM_RE`, `_PROB_RANGE_RE`, `_PROB_DECIMAL_RE` and `_PROB_PERCENT_RE` match their backend counterparts (`backend/app/utils/actors.py:2685-2703`) character for character. The comment explains that Chinese rendering stays "（NN%）" because older backend builds misread "概率 15%" as 1.0 (`deerflow_bridge/linear_research.py:1546-1549`).
- `_probability_text` (`deerflow_bridge/linear_research.py:1562-1567`) tries range, then decimal, then percent.
- `_probability_value` (`deerflow_bridge/linear_research.py:1570-1584`) takes the midpoint of all numbers, dividing by 100 if `%` appears or any number is > 1. It returns a value in (0, 1], rounded to 6 places.
- `_is_scenario_heading` (`deerflow_bridge/linear_research.py:1587-1595`) needs a scenario cue. The heading must carry no probability, or carry exactly a 100% aggregate with aggregate wording.
- `_strip_probability_annotation`, `_bold_item_probability` (which looks in the bold text, then in the first 60 chars before a colon), and `_add_scenario_row` (`deerflow_bridge/linear_research.py:1598-1618`).
- **`parse_report_scenarios(report_md)`** (`deerflow_bridge/linear_research.py:1621-1653`) is the mirror of `forecast_inputs_from_report_markdown` (`backend/app/utils/actors.py:2770-2846`) [verifier: the backend function spans backend/app/utils/actors.py:2765-2831; 2832-2846 is `_VALENCE_TRAJECTORY` / `project_relationships`]:
  - For each scenario heading, it scans until a heading of the same or higher level.
  - Deeper headings or bold list items that carry a probability become rows.
  - The first section with 2–6 rows whose midpoints sum to 0.9–1.1 wins. Otherwise it returns `[]`.
  - Difference: the backend keeps ranges as `probability_band`, while the mirror stores the midpoint in `probability`.
- `scenarios_match_frame(parsed, frame)` (`deerflow_bridge/linear_research.py:1656-1659`) compares sets of `(_name_key, round(weight/100, 4))` and requires equal lengths.
- **`render_scenario_block(frame, language)`** (`deerflow_bridge/linear_research.py:1662-1671`):
  - It writes `### Scenario Probability Distribution` (or `### 情景概率分布`), then one row per scenario.
  - EN rows: `- **Name (NN% probability):** thesis`. ZH rows: `- **名（NN%）**：thesis`.
  - Probe: for EN and ZH, the block round-trips through `parse_report_scenarios`, and `scenarios_match_frame` returns True.
  - It is used at 3211.
- `neutralize_scenario_markup(body)` (`deerflow_bridge/linear_research.py:1674-1697`) un-bolds bold list items that carry a probability and strips the probability from `###`-and-deeper headings. `##` headings are left alone. It returns `(text, changed_count)` and is used only when the report fails validation (5243-5245).
- `_scenario_name_pattern` (`deerflow_bridge/linear_research.py:1700-1703`) adds a Latin word boundary in front of a name.
- Weight building blocks (`deerflow_bridge/linear_research.py:1706-1729`): `_WEIGHT_HEDGE` (about, ~, 约, …), `_WEIGHT_NUM`, `_PROBABILITY_WORDS`, `_PROBABILITY_CUE_RE`, `_CONDITIONAL_CUE_RE` (if/unless/would/could/might/若/如果/上调/下调…), `_WEIGHT_CHANGE_RE`, `_WEIGHT_UNIT_RE` (a sentence or list item), and `_BOUND_PROBABILITY_RE`. Possessive quantifiers keep matching linear-time.
- `_weight_patterns(names)` (`deerflow_bridge/linear_research.py:1732-1772`) defines 11 patterns of three kinds:
  - **paren**: a probability-only parenthetical, or `(p=0.45)` decimals;
  - **explicit**: forms such as "carries a 45% probability", "Base case probability: 45%", "概率为45%", "a 45% probability of the Base case", or a list item led by the name;
  - **loose**: forms such as "Base case at 45%", "Base case: 45%", "为35%", "a 45% Base case".
- `_frame_names_pattern(frame)` (`deerflow_bridge/linear_research.py:1775-1778`) orders names longest first and maps casefolded names to scenarios.
- `_weight_units(text)` (`deerflow_bridge/linear_research.py:1781-1783`).
- **`fix_scenario_weights(body, frame)`** (`deerflow_bridge/linear_research.py:1786-1847`) rewrites restated frame weights to the frame value:
  - Matches are collected per number offset; the first pattern wins.
  - A loose match counts only in a unit that names a probability, or that restates at least 2 scenarios summing to 100 ± 1.
  - Non-paren matches in a unit with conditional wording are skipped.
  - Decimals are rewritten as decimals (`0.5`).
  - Returns `(text, fixes[{name, from, to}])`.
  - Probe: "(45%)" became 50 and "carries a 55% probability" became 50; "would fall to 10% if" was left alone.
  - Used at 5221, 5224 and 5438.
- **`scenario_weight_conflicts(body, frame)`** (`deerflow_bridge/linear_research.py:1850-1870`) is lint only and never rewrites. It flags units that name exactly one frame scenario, carry a probability-bound percentage that differs from the frame, and contain no conditional or change wording. It returns units collapsed to 200 chars and is used at 5439.
- `_SCENARIO_ROW_RE` (`deerflow_bridge/linear_research.py:1879-1883`) and **`strip_extra_scenario_probabilities(body, frame)`** (`deerflow_bridge/linear_research.py:1886-1909`): a list row that gives a **non-frame** scenario a probability loses that probability, unless the row cites `[S#]`. Probe: `- **Tail risk (5% probability):** rare` became `- Tail risk: rare`, while the cited "Market odds (12%) … [S3]" row was kept. Used at 5232 and 5236.

### 13. Citations, research notes and number verification (1912–2746)

**Citation regexes** (`deerflow_bridge/linear_research.py:1916-1957`):
- `_CITE_RE` = `\[S(\d{1,9})\]`, the canonical marker (at most 9 digits, so `int()` cannot blow up).
- `_CITE_GROUP_RE` matches any bracketed citation group: `[S3, S5]`, `【S3】`, `(S3)`, `[Source 3]`, `[S3-S5]`, `[S30, p. 4]`.
- `_CITE_MEMBER_RE` and `_CITE_RANGE_MAX=20`.
- `_CITE_NAME_BEFORE_RE`: a product or standard word before `(S24)` means the text is prose ("flagship (S24)", "ISSB standards (S1, S2)").
- `_STALE_CITE_GROUP_RE` and `_STALE_CITE_PROSE_RE`.
- `_TAG_RE` and `_TAG_MAP`, which map the Chinese tags 已核实/已验证 to VERIFIED, 据报道 to REPORTED and 未核实 to UNVERIFIED.

**Notes-parsing regexes** (`deerflow_bridge/linear_research.py:1962-1989`):
- `_BULLET_RE` covers `-*•·–—+▪◦●`, `1.`/`1)`, `**1.**`, `1、`, `(1)` and `①…⑳`.
- `_NOTE_SECTIONS` holds EN and ZH aliases for findings, conflicts, open_questions and discovered.
- `_NOTE_HEADING_*` (max 120 chars, plus wrapper and KIQ-id prefix/suffix strippers).
- `_ROW_DOMAIN_TAIL_RE` and `_TIER_GROUP_RE`, used for the "— domain (S3)" tier labels.

**Number regexes** (`deerflow_bridge/linear_research.py:1993-2042`):
- `_DATE_LIKE_RE`: real calendar dates only, never "1050.5".
- `_NUMBER_RE`, `_THOUSANDS_RE`, `_SPACED_GROUPS_RE`.
- `_SCALED_NUMBER_RE` and `_SCALE_EXPONENTS`: thousand/million/…/k/m/b/t, plus 万/亿/万亿 and others.
- `_PERCENT_*`: %, percent, pct, pp, pts, 个百分点, wrapped lines and split table cells.

**Number functions:**
- `_canonical_numbers` (`deerflow_bridge/linear_research.py:2045-2053`).
- `_percent_numbers` (`deerflow_bridge/linear_research.py:2056-2060`).
- `_percent_context_numbers` (`deerflow_bridge/linear_research.py:2063-2097`) collects numbers from percent-marked tables (header among the first 3 rows, or a caption) and from flattened header blocks.
- `_page_percent_numbers` (`deerflow_bridge/linear_research.py:2100-2103`).
- `fact_percent_tokens` (`deerflow_bridge/linear_research.py:2106-2109`).

**Unit classes** (`deerflow_bridge/linear_research.py:2112-2186`):
- `power`: W family, 千瓦, 兆瓦, …, but not 千瓦时.
- `energy`: Wh family, 千瓦时, 度电.
- `currency`: dollars, euros, yuan, ISO codes and 元, plus prefix signs (`$`, `US$`, `€`, `Rs`, 人民币).

Number-plus-unit patterns may cross up to two line breaks (KPI cards). The range-low/high and sign-after patterns live here too.

**Unit functions:**
- `_unit_context_lines` (`deerflow_bridge/linear_research.py:2189-2228`): table rows whose caption (up to 3 lines above) or any row names the unit, plus labelled lines and the lines under them up to a blank line.
- `_page_unit_numbers` (`deerflow_bridge/linear_research.py:2231-2254`) emits `"<unit>:<n>"` and `"<unit>:=<full>"`.
- `fact_unit_tokens` (`deerflow_bridge/linear_research.py:2257-2271`) returns `{number: {unit classes}}`, for suffix or prefix units only.

**Citation functions:**
- `_SENTENCE_RE` (`deerflow_bridge/linear_research.py:2276`).
- `_citation_numbers(body)` (`deerflow_bridge/linear_research.py:2279-2293`): `S3-S5` expands to 3, 4, 5 only if `start < end ≤ start+20`; otherwise it yields both endpoints. Output is deduplicated in order.
- **`normalize_citations(text)`** (`deerflow_bridge/linear_research.py:2296-2326`) rewrites every citation group to canonical `[S<n>]` runs. It leaves these alone:
  - mismatched brackets;
  - groups without an `S` and without a source prefix;
  - round-bracket groups that have a label or `&`, have a member without `S`, or follow a product or standard word.

  A row-header tier label `— agency.org (S3)` becomes `(tier 3)` via `rg.tier_label` (`deerflow_bridge/research_gateway.py:2911-2919`).

  Probe: `[S3, S5]` → `[S3][S5]`; `[S3-S5]` → `[S3][S4][S5]`; `[S30, p. 4]` → `[S30]`; "flagship (S24)" and `[S1 and S2]` unchanged. Used at 5254.
- **`strip_stale_citations(text)`** (`deerflow_bridge/linear_research.py:2329-2346`) removes square or CJK groups that are not canonical (`[S1 and S2]`) and returns `(text, removed)`.
- **`stale_citation_tokens(text)`** (`deerflow_bridge/linear_research.py:2349-2359`) is QA lint for prose pointers such as "according to S30" and "Source 12". Used at 5440.
- `_tidy_spaces` (`deerflow_bridge/linear_research.py:2362-2371`) collapses double spaces and removes spaces before punctuation, keeping indentation.
- **`strip_unknown_citations(text, known)`** (`deerflow_bridge/linear_research.py:2374-2386`) drops markers for which `known(sid)` is false and returns `(text, kept sids in first-seen order)`.

**Canonical numbers:**
- `_canonical_number` (`deerflow_bridge/linear_research.py:2389-2397`) strips leading zeros and trailing fractional zeros, and rejects strings with more than one ".".
- `_YEAR_RANGE_RE` and `_strip_year_ranges` (`deerflow_bridge/linear_research.py:2402-2407`) remove "2025-26" or "FY2025/26" only when the end year is start+1.
- `_number_text(text, strip_dates)` (`deerflow_bridge/linear_research.py:2410-2416`) applies NFKC and removes `[S#]` markers; optionally it also removes dates and year ranges.
- `_join_digit_groups` (`deerflow_bridge/linear_research.py:2419-2421`) turns "12 500" or "12'500" into 12500.
- `_number_pieces`, `_numbers_in`, `_number_values`, `_number_values_at` (`deerflow_bridge/linear_research.py:2424-2468`): a scaled number carries its full value as `"=<decimal>"` (`1.2 trillion` = `=1200000000000`). Single-letter scales count only after a currency sign.
- **`fact_number_tokens(text)`** (`deerflow_bridge/linear_research.py:2471-2477`) collects the numbers a VERIFIED fact must share with its page: those with ≥ 2 digits or a decimal point, after dates and year ranges are stripped. **Single-digit integers are never checked; bare years are** (probe).
- `fact_number_values` (`deerflow_bridge/linear_research.py:2480-2490`).
- **`page_number_set(text)`** (`deerflow_bridge/linear_research.py:2493-2506`) returns a frozenset of tokens in four namespaces:
  - the literal number (`"176"`);
  - the full value (`"=176"`, `"=1200000000000"`);
  - the percentage (`"%4.4"`);
  - the unit (`"power:176"`, `"currency:=1.2e12…"`).

  It is computed once per page and cached in `_Engine.page_numbers` (4105-4116).
- `_number_on_pages(token, available, values, percent, units)` (`deerflow_bridge/linear_research.py:2509-2521`) applies three rules:
  - a percentage matches only a page percentage;
  - a number with a unit matches only the same unit class, as written or at the same full value;
  - any other number matches literally or by full value.

**Notes-heading detection:**
- `_note_heading(line)` (`deerflow_bridge/linear_research.py:2524-2537`) runs twice: it strips wrappers, numbering and KIQ-id prefix/suffix, then requires the whole remainder to be a section alias. Lines longer than 120 chars return None.
- `_inline_note_label(line)` (`deerflow_bridge/linear_research.py:2540-2548`) recognises "Conflicts: …" when the colon is within the first 60 chars.
- `has_notes_heading` (`deerflow_bridge/linear_research.py:2551-2553`).
- **`has_notes_structure(text)`** (`deerflow_bridge/linear_research.py:2556-2572`) is true if any line is a notes heading, or is a bullet that cites a source after normalisation. It is the lenient "the agent has answered" detector (3550, 3613). Probe: `"- fact [S1]"` → True; a reply with no heading or cited bullet → False.
- `_HSPACE_RUN_RE`, `_TABLE_TAG_CELL_RE`, `_table_cells` (`deerflow_bridge/linear_research.py:2575-2586`). A separator row returns None, and a bare tag cell becomes "(VERIFIED)".
- `_line_items(line)` (`deerflow_bridge/linear_research.py:2589-2599`) splits a line into one item per sentence when every sentence cites a source. Lines that hold only markers, or are short labels, yield nothing.
- **`_parse_note_sections(notes)`** (`deerflow_bridge/linear_research.py:2602-2660`) is a line state machine:
  - A heading switches the section.
  - A non-section `#` line resets the wrap state.
  - A bullet becomes a new item.
  - A plain line following a bullet continues it.
  - Table rows become items; the header row before a `|---|` separator is popped.
  - An inline label switches the section.
  - Under a heading, a plain line becomes items via `_line_items`.
  - Before any heading, plain lines are "loose".
  - Items are filed under their section only if some heading was seen; otherwise everything is findings.
  - With no items and no heading, loose lines of ≥ 20 chars become findings.
- `_split_tag(text)` (`deerflow_bridge/linear_research.py:2663-2671`) uses the **last** tag match. The default is REPORTED, and the tag is removed from the text.
- **`postprocess_notes(kiq_id, notes, ledger_get, page_numbers)`** (`deerflow_bridge/linear_research.py:2674-2746`):
  1. Collapses horizontal space runs, then runs `normalize_citations` and `strip_unknown_citations` (known means `ledger_get(sid)` is not None). This gives the cleaned markdown.
  2. Parses the sections.
  3. For each finding: split the tag, strip unknown markers, and skip text shorter than 3 chars. A finding with no surviving marker goes to `unsourced`.
  4. Otherwise it becomes a fact `{kiq, text, sids, tag, verified_numbers: None}`. If the tag is VERIFIED:
     - With no cited sid whose ledger row has `fetched` set, the tag becomes REPORTED with `verification="no_fetched_source"`.
     - Otherwise every fact number token must be on the union of those pages' number sets. If it is, `verified_numbers=True`. If not, the tag becomes UNVERIFIED with `missing_numbers=[…]`.
  5. Conflicts, open questions and discovered leads also have unknown markers stripped.
  6. Returns `(cleaned_md.strip(), {"facts", "unsourced", "conflicts", "open_questions", "discovered"})`.
- Probe results:
  - `176 TWh in 2023 [S1]` against a fetched page containing both numbers stays VERIFIED;
  - `25 GW` against a page with only "20 GW" becomes UNVERIFIED with missing `25`;
  - a VERIFIED fact citing only an unfetched snippet becomes REPORTED with `no_fetched_source`;
  - a marker to an unknown `[S9]` leaves the finding in `unsourced`;
  - `$1.2 trillion` matches `$1,200 billion`; `$34 billion` does not match `$3.4 billion`;
  - "15%" is not verified by "May 15";
  - `12,500` matches `12 500`.
- In the engine, `ledger_get` is restricted to sids the agent was shown (4557-4561). The record is written to `v3/kiq/<id>.md` and `.json` *before* `mark_kiq` (4563-4579).

### 14. Deterministic page sentences (2749–2845)

- Regexes for page chrome (`deerflow_bridge/linear_research.py:2753-2771`): `_PAGE_CHROME_RE` (privacy, terms, ©, sign in, N min read, 版权所有, …), `_COOKIE_RE` together with `_COOKIE_CONTEXT_RE`, `_DATELINE_RE`, `_NAV_ROW_RE` (2 or more `|·•»›` separators make a menu or byline), `_MD_LINK_RE`, `_BARE_URL_RE`, `_RULE_LINE_RE`, and `_WRAPPED_LINE_MIN_CHARS=60`.
- `_is_page_chrome` and `_ends_sentence` (`deerflow_bridge/linear_research.py:2774-2780`).
- `_page_sentences(text)` (`deerflow_bridge/linear_research.py:2783-2819`):
  - Lines of a paragraph join only while the previous line is wrapped prose (≥ 60 chars with no end punctuation).
  - Headings, table rows, images, rules, setext titles and menu rows are skipped.
  - Link targets and bare URLs are dropped.
  - The result is split into sentences.
- **`numeric_sentences(text, limit=2, terms=())`** (`deerflow_bridge/linear_research.py:2822-2845`) keeps sentences of 30–400 chars that contain a digit and are not page chrome, deduplicated. With `terms`, sentences are scored by `rg._score_block` (`deerflow_bridge/research_gateway.py:3061-3071`) and the top `limit` with a score > 0 are returned in page order. Otherwise the first `limit` sentences are returned. Used by `KiqAgent.fallback_notes` for the deterministic REPORTED notes (3807-3830). Probe: menu, dateline and cookie lines are excluded, and the "capacity" term selects the GW sentence.

### 15. Evidence digest (2848–2922)

- `_TAG_ORDER` (`deerflow_bridge/linear_research.py:2852`) orders facts VERIFIED, then REPORTED, then UNVERIFIED.
- `_LINE_PRIORITY` (`deerflow_bridge/linear_research.py:2854`) sets the drop order: open questions (1) go first, then UNVERIFIED (2), REPORTED (3), conflict (4) and VERIFIED (5).
- `_is_sourced(fact)` (`deerflow_bridge/linear_research.py:2857-2860`) requires a dict whose text has an `[S#]`. It filters legacy records that still carry findings without markers.
- `_kiq_digest_block(record, cap, language)` (`deerflow_bridge/linear_research.py:2863-2893`) builds `### <id> — <question>`, then `Findings:` (sorted by tag; `(no findings recorded)` when empty), then `Conflicts:`, then `Open questions:`. While `len(header)+60+Σ(line+1) > cap`, it drops the lowest-priority line, and on a tie the latest one. Lines are never cut. Returns `(block, dropped)`.
- **`build_digest(records, ledger_get, digest_cap, language)`** (`deerflow_bridge/linear_research.py:2896-2922`):
  - Records are sorted by `_natural_key`.
  - Each block gets `int(min(12000, max(3000, digest_cap/n)))` chars.
  - The SOURCE INDEX lists every cited sid in ascending order as `[S<n>] title — domain (tier N, fetched|snippet)`.
  - The output is `"EVIDENCE DIGEST\n\n<blocks>\n\nSOURCE INDEX\n<index>"` together with the dropped count.
  - It is deterministic for a given input, which is what lets parallel writers share one byte-identical prefix (header at `deerflow_bridge/linear_research.py:2849`).
  - Used at 4797, and persisted as `v3/digest.md` (4793).

### 16. Writer output parsing (2925–3053)

- `_writer_heading(line)` (`deerflow_bridge/linear_research.py:2929-2946`) is a linear-time equivalent of `^\s{0,3}(#{1,2})\s+(.+?)\s*#*\s*$`. It returns the text of a `#` or `##` heading, or None. Indentation over 3 spaces, `###`, or a missing space after `#` give None.
- `_REFERENCE_HEADING_KEYS` (`deerflow_bridge/linear_research.py:2949-2951`).
- `_match_title(heading, candidates)` (`deerflow_bridge/linear_research.py:2954-2966`) tries an exact `_section_title_key`, then the best `difflib` ratio ≥ 0.8. Also used in QA critique mapping (5411).
- `_names_title(heading_key, title_key)` (`deerflow_bridge/linear_research.py:2969-2978`) accepts a prefix match when the shorter key has at least 4 Latin or 2 CJK chars, or containment at twice that minimum.
- **`split_writer_output(text, assigned, demoted=None)`** (`deerflow_bridge/linear_research.py:2981-3053`):
  1. Splits on `#`/`##` headings outside ``` fences.
  2. Pass 1: exact or near-exact title match.
  3. Pass 2: a drifted heading that names exactly one remaining title.
  4. Pass 3: when there are ≥ 2 assigned titles and the unmatched headings equal the unmatched titles in number, assign by position, but only if section order stays monotonic.
  5. Unmatched non-reference headings are demoted to `### heading` and appended to the previous matched section. If no section has matched yet, they are stashed and prepended to the next match. `demoted` collects `(title, heading, block)`.
  6. References-like and empty sections are dropped.
  7. A single-section reply with no matched heading puts the preamble and stash under that one title.

  Probe: `## Background` → "Background and Current State" via pass 2; `## Extra Thing` was demoted into it; `## References` was dropped. Used at 5027, 5077, 5146 and 5371.

---

## Control flow

How the slice is driven. Line numbers ≥ 3056 are in the same file, outside this slice.

1. **Engine selection (outside the file).**
   - The orchestrator normalises `RESEARCH_ENGINE` (v3|linear → v3; legacy|deerflow|agentic → legacy; unknown → v3 with a warn) (`backend/app/services/pipeline_orchestrator.py:5888-5934`).
   - It forces legacy for evidence-only and synthesis-manifest lanes.
   - For v3 it sets `env["RESEARCH_ENGINE"]` and `DEERFLOW_RESEARCH_TIMEOUT` to the effective watchdog budget (`backend/app/services/pipeline_orchestrator.py:2290-2307`). [verifier: `env["RESEARCH_ENGINE"]` is set for every research launch, legacy included; only `DEERFLOW_RESEARCH_TIMEOUT` is v3-only (backend/app/services/pipeline_orchestrator.py:2295-2301, backend/app/services/pipeline_orchestrator.py:2302-2307)]
   - It forwards `RESEARCH_MODEL_CONCURRENCY_GLOBAL` (`backend/app/services/pipeline_orchestrator.py:2369-2371`).
   - In the child, `_resolve_research_engine` maps v3/linear → v3; **unset → legacy** (`deerflow_bridge/deerflow_research.py:16381-16400`).
   - `_legacy_only_mode` sends `--extract-only`, `--evidence-only` and `--synthesis-manifest` to legacy (`deerflow_bridge/deerflow_research.py:16403-16415`, `deerflow_bridge/deerflow_research.py:16678-16689`).
   - `_dispatch_v3_engine` then runs `import linear_research` and `linear_research.run(..., bridge=_bridge_module())`. Any exception or a non-int return becomes `meta.status=failed` and rc 2 (`deerflow_bridge/deerflow_research.py:16516-16541`).
2. **`run` (6326) → `_Engine.__init__`** (3946-4005):
   - `resolve_preset(args.depth, env)` (3960) and `detect_language(question, args.target_language)` (3961);
   - `actor_cast_max(env)` through `_actor_cap` (3962, 4132-4134);
   - the identity, then `_open_work_dir(... writer=self._write_internal ...)` (3969-3975);
   - the ledger, `ToolLimits` from the preset (planner gets 6 searches; the seeder gets `2×(max_kiqs + gap_rounds×followups)`) (3978-3988);
   - `_CallTally` wrapping `gateway.invoke` (3995-3996);
   - a run `Deadline(preset.time_budget_s)` (4003).
3. **Plan** (`phase_plan`, 4203-4232):
   - If `state.is_done("plan")`, try `Plan.from_dict(plan.json)` together with `brief.md`. An outage plan with no facts gathered is discarded (`_discard_outage_plan` 4234-4254).
   - Otherwise:
     1. `render_pre_brief`;
     2. `_plan_calls` (4311-4347): scope JSON via `_T_SCOPE`; scout searches through `_scout`, a `fan_out` of `tools.search(q, agent_id="planner")` capped at 6,000 chars (4349-4361); then plan JSON via `_T_PLAN`;
     3. `build_plan`;
     4. `PLAN_OUTAGE_KEY` on an outage;
     5. `render_brief`;
     6. atomic writes of `plan.json` and `brief.md`;
     7. `state.set_phase("plan","done")`.
   - `replan_after_outage` (4256-4291) re-runs `_plan_calls(single_attempt=True)` + `build_plan` once if ≥ 75% of the time remains.
4. **Gather**:
   - `KiqAgent` (3422) binds `AGENT_TOOLS` on every call (3563-3621).
   - It injects `NOTES_NUDGE_TEXT`, `STOP_TEXT`, `TOOL_BUDGET_TEXT`, `TOOL_CALLS_SKIPPED_TEXT`, `DUPLICATE_CALL_TEXT`, `ALREADY_READ_TEXT` and `STORED_READS_EXHAUSTED_TEXT` (3531-3769).
   - It decides "answered" with `has_notes_structure` / `has_notes_heading` (3550, 3613).
   - The KIQ task is `_T_KIQ_TASK` plus `_KIND_EMPHASIS` and seeds under `LABEL_SEEDS` (4627-4631).
   - The fan-out is primed with `PRIME_TASK` (4492).
   - Each finished agent goes through `postprocess_notes(..., self.page_numbers)` (4563), with `page_numbers` backed by `page_number_set` (4113). Then `kiq/<id>.md`, `kiq/<id>.json` and `state.mark_kiq` are written in that order (4576-4578).
   - Fallback notes use `numeric_sentences` (3812, 3824).
5. **Gap**: `_T_GAP` (4737); ordering by `_natural_key` (4736, 4771); follow-ups reloaded via `Kiq.from_dict` (4373, 4703).
6. **Synthesize**:
   - `build_digest` (4797) → `digest.md`;
   - section prompts with `_SECTION_RULES` and `_SCENARIO_SECTION_NOTE` (4938-4939);
   - `split_writer_output` (5027…);
   - the canonical block via `render_scenario_block` (3211);
   - exec summary via `_T_EXEC` (5142).
7. **QA**:
   - `fix_scenario_weights` (5221, 5224) and `strip_extra_scenario_probabilities` (5232, 5236);
   - `parse_report_scenarios` + `scenarios_match_frame`, with `neutralize_scenario_markup` on failure (5242-5250);
   - `normalize_citations` + `strip_stale_citations` (5254);
   - lint via `scenario_weight_conflicts` and `stale_citation_tokens` (5439-5440);
   - critique via `_T_CRITIQUE` (5390) + `_match_title` (5411).
8. **Finalize**: `_T_ACTORS` / `_T_FACTS` extraction (5626-5628); `MIN_REPORT_CHARS` gate (5531-5533); a SIGTERM raises `RunTerminated` (6291, 6312, 6361). [verifier: raised only at 6312; 6291 is docstring text and 6361 only classifies the exception (deerflow_bridge/linear_research.py:6306-6312, deerflow_bridge/linear_research.py:6361)]

---

## Data & artifacts

Files this slice reads or writes directly, or defines the format of:

| Path | Writer / reader in slice | Format / key fields | Anchor |
|---|---|---|---|
| `out_dir/v3/state.json` | `_RunState.fresh/save/set_phase/mark_kiq`; read by `_open_work_dir` | `{engine_version, identity{question_sha256, depth, model, language, engine_version}, created_at, phases{<phase>{status, started_at?, finished_at?, detail≤500}}, kiqs{<id>{status, facts, verified, fallback, finished_at}}}`. The kiq info keys come from 4578 | `deerflow_bridge/linear_research.py:903-956`, `deerflow_bridge/linear_research.py:973-995`, `deerflow_bridge/linear_research.py:3969-3971` |
| `out_dir/v3.stale-<YYYYMMDDTHHMMSSZ>[-n]/` | `_open_work_dir` renames a `v3/` from a different identity, or an unreadable one | directory archive | `deerflow_bridge/linear_research.py:963-970`, `deerflow_bridge/linear_research.py:990-993` |
| `out_dir/v3/plan.json` | schema `Plan.to_dict`; reload `Plan.from_dict` (written at 4225, read at 4204) | question, language, as_of, restated_question, horizon, kiqs[{id, question, queries, kind, why, round}], sections[{index, title, kiq_ids, focus, is_scenario}], scenarios[{name, weight, thesis}], actors[{name, type, why}], key_entities, scout_queries, fallback{scope?, plan?, kiqs?, sections?, scenarios?, unrouted_kiqs?, model_unavailable?} | `deerflow_bridge/linear_research.py:1105-1145`, `deerflow_bridge/linear_research.py:1468-1508` |
| `out_dir/v3/brief.md` | content from `render_brief` (written at 4226 / 4288) | plain-text RUN BRIEF (see §11) | `deerflow_bridge/linear_research.py:1515-1540` |
| `out_dir/v3/kiq/<id>.md`, `.json` | content from `postprocess_notes` (written at 4576-4577) | md = cleaned notes. json = `{id, question, kind, round, facts[{kiq, text, sids, tag, verified_numbers, verification?, missing_numbers?}], unsourced[], conflicts[], open_questions[], discovered[], sources, stats, finished_at}` | `deerflow_bridge/linear_research.py:2674-2746` |
| `out_dir/v3/digest.md` | content from `build_digest` (4793-4797) | `EVIDENCE DIGEST … SOURCE INDEX …` | `deerflow_bridge/linear_research.py:2896-2922` |

In-memory structures: `Preset` (`deerflow_bridge/linear_research.py:647-669`), `Kiq`/`OutlineSection`/`Scenario`/`Plan` (`deerflow_bridge/linear_research.py:1040-1145`), `_CallTally._counts` (`deerflow_bridge/linear_research.py:858`), and the page-number token namespaces (`deerflow_bridge/linear_research.py:2493-2506`).

---

## Config / env knobs

All are read through the `env` mapping (normally `os.environ`, `deerflow_bridge/linear_research.py:711`; passed at 6346) and never written.

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `RESEARCH_LINEAR_MAX_KIQS` | 4/7/10 | Number of plan KIQs | `deerflow_bridge/linear_research.py:616-631`, `deerflow_bridge/linear_research.py:719-734` |
| `RESEARCH_LINEAR_AGENT_MAX_STEPS` | 5/7/9 | Tool rounds per agent | same |
| `RESEARCH_LINEAR_SEARCHES_PER_KIQ` / `_FETCHES_PER_KIQ` | 3,3 / 4,4 / 5,6 | Per-agent tool budget | same |
| `RESEARCH_LINEAR_MAX_SEARCHES_TOTAL` / `_MAX_FETCHES_TOTAL` | 30,24 / 70,50 / 140,110 | Run totals. Auto-raised to the schedule unless explicit | `deerflow_bridge/linear_research.py:739-747` |
| `RESEARCH_LINEAR_GAP_ROUNDS` / `_FOLLOWUPS_PER_ROUND` | 0,0 / 1,3 / 2,4 | Gap rounds | `deerflow_bridge/linear_research.py:616-631` |
| `RESEARCH_LINEAR_SECTIONS_MIN` / `_SECTIONS_MAX` | 6–8 / 8–12 / 11–16 | Outline size clamp. min>max forces min=max | `deerflow_bridge/linear_research.py:735-738`, `deerflow_bridge/linear_research.py:1302-1333` |
| `RESEARCH_LINEAR_TARGET_UNITS` | 3000/6000/11000 | Report length target | `deerflow_bridge/linear_research.py:616-631` |
| `RESEARCH_LINEAR_CRITIQUE` | 0/0/1 | Critique pass. Bool words only | `deerflow_bridge/linear_research.py:672-679` |
| `RESEARCH_LINEAR_BUDGET_UNITS` | 1.2M/2.5M/5M | Weighted token budget | `deerflow_bridge/linear_research.py:616-631` |
| `RESEARCH_LINEAR_TIME_BUDGET_S` | 1200/2700/5400 | Wall clock | same |
| `RESEARCH_LINEAR_WORKERS` | 4 | Fan-out width | same |
| `RESEARCH_LINEAR_DIGEST_CAP` | 30k/60k/90k | Digest char budget | `deerflow_bridge/linear_research.py:2905` |
| `RESEARCH_LINEAR_MAX_TOKENS_EXTRACT` | 32,000 | Extraction output cap (floored at the JSON cap at 4005) | `deerflow_bridge/linear_research.py:155-159` |
| `RESEARCH_MODEL_CONCURRENCY_GLOBAL` | unset | Caps `workers` when an int ≥ 1. Set by the orchestrator | `deerflow_bridge/linear_research.py:748-754`; `backend/app/services/pipeline_orchestrator.py:2369-2371` |
| `DEERFLOW_RESEARCH_TIMEOUT` | unset | `time_budget_s = min(preset, 0.85×value)` | `deerflow_bridge/linear_research.py:755-761`; `backend/app/services/pipeline_orchestrator.py:2302-2307` |
| `ACTOR_CAST_MAX` | 20 | Cast cap for plan and extraction; 0 disables it | `deerflow_bridge/linear_research.py:1425-1438` |

The other `RESEARCH_LINEAR_*` knobs listed in `.env.example:159-169` are not read in this slice: `MAX_TOKENS_{AGENT,JSON,WRITE}`, `TIMEOUT_*`, `GLM_EFFORT_*` and `MODE`. The token, timeout and GLM-effort knobs are read in `deerflow_bridge/research_gateway.py:727-748`; `MODE` is read at `deerflow_bridge/linear_research.py:4178`.

---

## External calls

- **No direct LLM, HTTP, subprocess or DB calls occur in lines 1–3055.** Every model, search and fetch call is made by part 2 through `rg.ModelGateway` and `rg.ResearchTools`. This slice only supplies prompts, schemas and the parsing of what comes back.
- Filesystem:
  - `_read_json` / `_read_text` (`deerflow_bridge/linear_research.py:595-606`);
  - `_RunState.save` through the injected atomic writer (`deerflow_bridge/linear_research.py:912-914`);
  - `_open_work_dir`: `Path.rename` of the stale `v3/` plus `mkdir` (`deerflow_bridge/linear_research.py:983-994`).
- Gateway helpers used:
  - `rg.AGENT_TOOLS_SCHEMA` (`deerflow_bridge/linear_research.py:183`);
  - `rg.query_terms` (`deerflow_bridge/linear_research.py:1152`);
  - `rg.MAX_QUERY_CHARS` (`deerflow_bridge/linear_research.py:1161`, `deerflow_bridge/linear_research.py:1188`, `deerflow_bridge/linear_research.py:1501`);
  - `rg.tier_label` (`deerflow_bridge/linear_research.py:2318`, `deerflow_bridge/linear_research.py:2920`);
  - `rg._score_block`, a private gateway function (`deerflow_bridge/linear_research.py:2841`);
  - `rg.ContentFiltered` / `rg.BudgetExhausted` / `rg.GatewayError` (`deerflow_bridge/linear_research.py:874-881`; class definitions at `deerflow_bridge/research_gateway.py:113-176`).
- Signals: `signal.SIGTERM` gives the `RunTerminated` exit code (`deerflow_bridge/linear_research.py:843`).

---

## Cross-module edges

**Callers into this slice:**
- `deerflow_bridge/deerflow_research.py:16526-16530` calls `linear_research.run`, defined at 6326 (outside the slice); it uses everything here.
- Same file, part 2:
  - `_Engine.__init__` (3946-4005);
  - `phase_plan` / `replan_after_outage` / `_plan_calls` (4203-4347);
  - `KiqAgent` (3422-3830);
  - gather record writer (4555-4579);
  - gap (4703-4771);
  - synth (4793-5146);
  - qa (5221-5440);
  - finalize (5531-5633);
  - signal handling (6291-6361).
- Tests:
  - `backend/tests/test_research_engine_v3.py` (imports `lr`; e.g. `_PROMPT_TEMPLATES` at 423, `PHASES` at 781);
  - `backend/tests/test_research_engine_v3_round2.py` (`scheduled_tool_calls` at 569-577);
  - `test_research_engine_v3_{text,hardening,residuals,round3_*}.py` (re-use `lr` via `test_research_engine_v3`);
  - `backend/tests/test_bridge_overhaul_v3.py:89-102` (stubs `linear_research` in `sys.modules`).
- Deployment: `backend/app/services/pipeline_orchestrator.py:1358-1361` (`_DEPLOYED_BRIDGE_MODULES`), `setup.sh:592-603`, `backend/tests/test_deerflow_bridge_sync_guard.py:185-233`.

**Calls out of this slice:**
- `research_gateway` (see External calls).
- Mirrors that must stay in sync, kept by copying rather than by import:
  - `_name_key` ↔ `backend/app/utils/actors.py:145-156`;
  - scenario-parser regexes ↔ `backend/app/utils/actors.py:2685-2703`;
  - `parse_report_scenarios` ↔ `backend/app/utils/actors.py:2770-2846`;
  - `actor_cast_max` ↔ `deerflow_bridge/deerflow_research.py:2299-2312`.

---

## Invariants, gates, validation

- **KIQ ids** are engine-assigned `K1..Kn`; gap follow-ups use `G<r>F<n>`. Any other id is rejected on reload (`deerflow_bridge/linear_research.py:1010`, `deerflow_bridge/linear_research.py:1059`, `deerflow_bridge/linear_research.py:1186`).
- **Exactly one scenario section.** `_ensure_scenario_section` enforces it (`deerflow_bridge/linear_research.py:1280-1299`) and `Plan.from_dict` checks it again (`deerflow_bridge/linear_research.py:1132`).
- **Scenario frame:** 2–6 scenarios, integer weights summing to 100, each ≥ 1 (`deerflow_bridge/linear_research.py:1364-1380`, `deerflow_bridge/linear_research.py:1417-1422`, `deerflow_bridge/linear_research.py:1133-1134`). The rendered block must round-trip through the backend-parser mirror (`deerflow_bridge/linear_research.py:1621-1671`).
- **The plan never fails.** Every missing part has a deterministic fallback, recorded in `plan.fallback` (`deerflow_bridge/linear_research.py:1462-1508`). [verifier: the scenario-section insertion and the section merge/padding are silent repairs with no `plan.fallback` key (deerflow_bridge/linear_research.py:1487-1488, deerflow_bridge/linear_research.py:1508)]
- **Sections are within [sections_min, sections_max]** when possible (`deerflow_bridge/linear_research.py:1302-1333`; see Surprises for the case where it is not).
- **The brief is built once and reused byte-identically** for prompt caching (`deerflow_bridge/linear_research.py:1515-1516`). `ENGINE_CORE` is static and question-free (`deerflow_bridge/linear_research.py:221-225`). One `AGENT_TOOLS` object is bound on every agent call (`deerflow_bridge/linear_research.py:183`).
- **No literal `$` in templates.** A missing placeholder raises (`deerflow_bridge/linear_research.py:382-385`, `deerflow_bridge/linear_research.py:520-522`).
- **Work-dir identity binding:** artifacts from another question, depth, model, language or engine version can never leak into a run (`deerflow_bridge/linear_research.py:973-995`).
- **State writes are serialised** under an RLock and are atomic (`deerflow_bridge/linear_research.py:895-933`, `deerflow_bridge/research_gateway.py:2340-2355`).
- **VERIFIED gate:**
  - the finding cites a ledger-known sid;
  - at least one cited sid has `fetched`;
  - every ≥ 2-digit or decimal number is on those pages, matched by literal, full value, percent namespace or unit class.

  Otherwise the fact is demoted to REPORTED or UNVERIFIED (`deerflow_bridge/linear_research.py:2674-2729`). A finding without a surviving marker is never a fact (`deerflow_bridge/linear_research.py:2704-2706`).
- **Canonical citations** are `[S<n>]` with at most 9 digits. Ranges expand only up to 20 members. Unresolvable groups are removed, not published [verifier: only square/CJK-bracket groups are removed (`_STALE_CITE_GROUP_RE`, applied in QA at 5254); a non-canonical round-bracket group such as "(S1 and S2)" or "(S1 2025)" is deliberately left as prose (deerflow_bridge/linear_research.py:1950-1952, deerflow_bridge/linear_research.py:2315-2323)] (`deerflow_bridge/linear_research.py:1916-1936`, `deerflow_bridge/linear_research.py:2289-2292`, `deerflow_bridge/linear_research.py:2329-2346`).
- **Scenario-weight rewrites** touch only weight restatements, never conditional analysis or other figures (`deerflow_bridge/linear_research.py:1786-1847`). Extra scenario probabilities are dropped unless cited (`deerflow_bridge/linear_research.py:1886-1909`).
- **Regex performance:** many patterns use possessive quantifiers or manual stripping to stay linear-time on model whitespace (`deerflow_bridge/linear_research.py:1723-1729`, `deerflow_bridge/linear_research.py:1873-1878`, `deerflow_bridge/linear_research.py:1975-1978`, `deerflow_bridge/linear_research.py:2929-2934`). These need Python ≥ 3.11; the projects declare `>=3.12` (`deer-flow/backend/pyproject.toml:6`, `backend/pyproject.toml:7`).

---

## Failure modes & recovery

- **Invalid env knob** → the preset value is kept or clamped, and a note is added to `Preset.notes` (logged once by the engine). It never raises (`deerflow_bridge/linear_research.py:724-733`).
- **Corrupt or foreign `v3/state.json`** → the directory is archived to `v3.stale-*` and the run starts fresh (`deerflow_bridge/linear_research.py:983-995`).
- **Corrupt `plan.json`** → `Plan.from_dict` returns None, and the plan phase plans again (`deerflow_bridge/linear_research.py:1116-1137`, 4204). A non-numeric weight or round raises instead (see Surprises).
- **Model unreachable at planning** → a template plan flagged `model_unavailable`. It is re-planned once in the same attempt if ≥ 75% of the time remains, or re-planned on resume if no facts were gathered (`deerflow_bridge/linear_research.py:160-163`, `deerflow_bridge/linear_research.py:204-207`, 4234-4291).
- **KIQ cut short** (deadline, budget, unusable notes, truncation, provider) → the reason is in `_RETRYABLE_FALLBACKS`, and the KIQ is researched again on resume (`deerflow_bridge/linear_research.py:208-215`).
- **Agent produced no usable notes** → deterministic REPORTED notes are built from `numeric_sentences` on the fetched pages (`deerflow_bridge/linear_research.py:2822-2845`, 3807-3830).
- **Handled failure** → `_EngineFailure` sets `meta.status=failed` and exit 2, which is resumable (`deerflow_bridge/linear_research.py:834-835`, 4197-4200).
- **SIGTERM** → `RunTerminated` gives exit 143. The bridge records "v3 engine interrupted" only if the engine has not already set `failed`, then re-raises (`deerflow_bridge/linear_research.py:838-843`; `deerflow_bridge/deerflow_research.py:16542-16551`).
- **Telemetry failure** → swallowed by `_Reporter` (`deerflow_bridge/linear_research.py:821-827`).
- **Provider outcome accounting** → `_CallTally` lets finalize tell "the provider never answered" apart from "ran out of time" (`deerflow_bridge/linear_research.py:846-885`; docstring `deerflow_bridge/linear_research.py:51-53`).

---

## Surprises

1. **Default-engine disagreement (doc vs code).**
   - The orchestrator and Config default to v3 (`backend/app/config.py:1187`, `backend/app/services/pipeline_orchestrator.py:5906-5934`), and README says v3 is selected by "`RESEARCH_ENGINE=v3`, or unset" (`README.md:461`).
   - But the bridge's own resolver treats **unset as legacy** (`deerflow_bridge/deerflow_research.py:16384-16391`).
   - Pipeline runs are unaffected because the parent always sets the env var (`backend/app/services/pipeline_orchestrator.py:2301`). A direct CLI run of `deerflow_research.py` without the env var runs the legacy engine. [verifier: the facts hold, but "doc vs code drift" is overstated: README frames the choice as the orchestrator's ("The orchestrator picks one per pipeline and passes it to the research subprocess explicitly", README.md:457), and the bridge docstring documents unset → legacy as deliberate CLI/test backward compatibility (deerflow_bridge/deerflow_research.py:16384-16387)]
2. **The time budget can fall below its own floor (suspected).**
   - `_KNOB_BOUNDS` sets `time_budget_s` to at least 60 s (`deerflow_bridge/linear_research.py:639`).
   - But the `DEERFLOW_RESEARCH_TIMEOUT` cap is applied *after* clamping (`deerflow_bridge/linear_research.py:755-761`).
   - Probe: `DEERFLOW_RESEARCH_TIMEOUT=30` gives `time_budget_s=25.5`. [verifier: probe reproduced, but the order reads as intentional rather than a bug: the cap exists so the report lands before the watchdog's SIGKILL (deerflow_bridge/linear_research.py:701-704, README.md:519), and re-applying the 60 s floor would schedule past a 30 s watchdog. The orchestrator hands v3 the effective watchdog budget (backend/app/services/pipeline_orchestrator.py:2302-2307), so a sub-71 s value is an edge case]
3. **Locale strings other than the listed aliases break localisation (suspected).**
   - `detect_language` returns an unrecognised explicit target verbatim (`deerflow_bridge/linear_research.py:792`), e.g. `"zh-Hans-CN"` (probe).
   - `_lang_key` treats anything other than exactly `"Chinese"` as English (`deerflow_bridge/linear_research.py:373-375`).
   - Such a run gets English default KIQs, outline, frame and headings, while the prompts ask for prose in `"zh-Hans-CN"`.
4. **Number-verification strictness differs from README.**
   - A bare year in a VERIFIED fact must appear on the page. Dates and FY ranges are stripped, but "in 2023" is not. Probe: "176 TWh in 2023" against a page without "2023" becomes UNVERIFIED (`deerflow_bridge/linear_research.py:1993-1998`, `deerflow_bridge/linear_research.py:2471-2477`).
   - Single-digit integers are never checked (`deerflow_bridge/linear_research.py:2475`).
   - README says "every number in it appears on the page" (`README.md:501`).
5. **The `kiq/<id>.md` audit file keeps the model's original tags.**
   - `postprocess_notes` returns `cleaned_md` with markers normalised and unknown markers removed, but with the model's `(VERIFIED)` tags untouched. The corrected VERIFIED/REPORTED/UNVERIFIED tags exist only in `parts["facts"]` (`deerflow_bridge/linear_research.py:2693-2694`, `deerflow_bridge/linear_research.py:2740`).
   - Probe: "Capacity reached 25 GW … (VERIFIED)" stays VERIFIED in the md, while the json says UNVERIFIED.
   - The md is written at 4576 and never read back by the engine (grep), so it is misleading only to humans.
6. **The VERIFIED check uses a run-global `fetched` flag.**
   - ENGINE_CORE says VERIFIED needs a page "you fetched in this investigation" (`deerflow_bridge/linear_research.py:243`).
   - The code accepts any cited sid whose ledger row has `fetched` (`deerflow_bridge/linear_research.py:2710`). The ledger sets that flag run-wide (`deerflow_bridge/research_gateway.py:2517`), and the engine restricts `ledger_get` only to sids the agent was *shown* (4557-4561).
   - So a snippet-only sid that another agent fetched can verify a fact. The number-on-page check limits the risk.
7. **`_PROMPT_TEMPLATES` is test-only.** The registry (`deerflow_bridge/linear_research.py:482-492`) is never referenced by the engine, which uses the `_T_*` objects directly. Only `backend/tests/test_research_engine_v3.py:423-424` iterates it. A new template added without registration would escape the render test.
8. **`_HAN_RE` is defined in the language section but not used by `detect_language`.**
   - `_HAN_RE` is defined at `deerflow_bridge/linear_research.py:769` and used only at 3269.
   - The docstring says "20% … Han characters" (`deerflow_bridge/linear_research.py:781-783`), but the ratio counts all CJK, including kana and hangul (`deerflow_bridge/linear_research.py:796`).
   - Also, a Chinese question containing even one kana character is classified as Japanese (`deerflow_bridge/linear_research.py:799-800`).
9. **Quick fallback plan leaves default sections without KIQs.**
   - With `max_kiqs=4`, the template KIQs K5 (indicators) and K6 (base rates) are cut (`deerflow_bridge/linear_research.py:1160`).
   - The default outline still includes "Historical Base Rates" and "Leading Indicators and Signposts", which then have empty `kiq_ids` (`deerflow_bridge/linear_research.py:310-311`, `deerflow_bridge/linear_research.py:1256-1262`; probe).
10. **Sections the plan prompt forbids are not filtered.** `_T_PLAN` forbids intro, conclusion-only and exec-summary sections (`deerflow_bridge/linear_research.py:412`), but `_NON_BODY_TITLES` filters only summary and reference titles (`deerflow_bridge/linear_research.py:1017-1022`). Probe: a planner section "1. Intro" was kept as "Intro".
11. **`sections_min` may be unreachable (suspected edge).**
    - The padding pool has 16 titles per language, minus the scenario title and any overlap (`deerflow_bridge/linear_research.py:1320-1330`).
    - `sections_min` may be set up to 24 (`deerflow_bridge/linear_research.py:637`).
    - With a high `RESEARCH_LINEAR_SECTIONS_MIN`, the clamp silently ends below the minimum.
12. **Plan reload is not fully total (suspected, low).**
    - `Plan.from_dict` calls `int(s.get("weight") or 0)` (`deerflow_bridge/linear_research.py:1129`), and `Kiq.from_dict` calls `int(data.get("round") or 0)` (`deerflow_bridge/linear_research.py:1064`).
    - A non-numeric value in a hand-edited `plan.json` or gap round file raises `ValueError` instead of returning None ("re-plan").
13. **Tier-label range does not match the ledger (harmless).** `_TIER_GROUP_RE` accepts `(S1)`–`(S4)` as tier labels (`deerflow_bridge/linear_research.py:1989`), while the ledger's valid tiers are S1–S3 (`deerflow_bridge/research_gateway.py:2368`).
14. **The digest can exceed `digest_cap`.** The per-KIQ floor of 3,000 chars means the total exceeds the cap when `n > digest_cap/3000`, e.g. a lowered `RESEARCH_LINEAR_DIGEST_CAP` with many follow-ups (`deerflow_bridge/linear_research.py:2905`).
15. **The scheduled totals comment is not the caps.** The comment "quick 26/12, standard 66/40, deep 132/108" (`deerflow_bridge/linear_research.py:613-614`) gives the *schedule needs*, not the caps. The preset caps (30/24, 70/50, 140/110) already exceed them, so no auto-raise happens with default knobs (probe; README table at `README.md:515-517` lists the caps).
16. **A whitespace-only heading is accepted.** `_writer_heading("##  ")` returns `" "`, faithfully mirroring the original regex (`deerflow_bridge/linear_research.py:2944-2945`). `split_writer_output` then opens a block with an empty heading, which matches nothing and is demoted or dropped. Harmless edge.
17. **Mirror difference from the backend parser.** `parse_report_scenarios` stores a range's midpoint as `probability` (`deerflow_bridge/linear_research.py:1612-1618`), while the backend keeps `probability_band` (`backend/app/utils/actors.py:2746-2762`). The 0.9–1.1 sum gate is equivalent because both use the midpoint, so the validation outcome matches. The row shapes differ.

---

## Verification

Adversarial pass on 2026-10-11, branch `main`, against `deerflow_bridge/linear_research.py` as on disk. Method: read every cited range; pure-function probes (offline, `PYTHONDONTWRITEBYTECODE=1`, scripts kept in the session scratchpad, no LLM or network) for presets, `build_plan`, citations, notes verification, the scenario block, language detection and writer splitting.

**Verdict counts:** 37 statements checked: the 15 key claims, the 14 surprises handed over, and 8 non-confirmed findings out of roughly 30 additional Walkthrough and Control-flow statements spot-checked. Result: **25 confirmed, 12 imprecise, 0 refuted, 0 unverifiable.**

### Non-confirmed claims, with corrections

1. **Key claim: `_open_work_dir` reuse rule (imprecise).** Reuse also requires `phases` and `kiqs` in `state.json` to be dicts. If the identity matches but either is not a dict, `v3/` is still archived (`deerflow_bridge/linear_research.py:986-993`). The map body (§10) states this correctly; only the summary claim omits it.
2. **Key claim: "each fallback used is recorded in `plan.fallback`" (imprecise).** Only `scope`, `plan`, `kiqs`, `sections`, `scenarios` and `unrouted_kiqs` are recorded (`deerflow_bridge/linear_research.py:1468-1508`). A default scenario section inserted by `_ensure_scenario_section`, and sections merged or padded by `_clamp_sections`, set no flag (`deerflow_bridge/linear_research.py:1487-1488`). Probe: planner sections "1. Intro" and "Market" with no scenario section produced `fallback == {}`, although "Scenarios and Probabilities" and three padding sections were added. The same overstatement appears in the Invariants bullet "The plan never fails" and is annotated there.
3. **Surprise 1: default-engine "doc vs code drift" (imprecise).** The facts hold:
   - unset → legacy in the bridge (`deerflow_bridge/deerflow_research.py:16389-16391`);
   - unset → v3 in the orchestrator (`backend/app/services/pipeline_orchestrator.py:5919-5922`, `backend/app/config.py:1187`).

   But README presents the engine choice as the orchestrator's: "The orchestrator picks one per pipeline and passes it to the research subprocess explicitly" (`README.md:457`). The bridge docstring documents unset → legacy as deliberate CLI and test compatibility (`deerflow_bridge/deerflow_research.py:16384-16387`). This is under-documented CLI behaviour rather than drift.
4. **Surprise 2: the `time_budget_s` 60 s floor is bypassed (imprecise).** The probe reproduces: a 30 s timeout gives 25.5 s. The cap's stated purpose, though, is to finish before the watchdog's SIGKILL (`deerflow_bridge/linear_research.py:701-704`, `README.md:519`). Applying the floor after the cap would schedule past the watchdog, so the current order is the safe one. Calling it a "bug" is not supported.
5. **`RunTerminated` raise sites, §10 and Control flow §8 (imprecise).** It is raised only at `deerflow_bridge/linear_research.py:6312`. Line 6291 is docstring text, and line 6361 is the `isinstance` check that sets `meta.error="terminated"` before re-raising. The SIGTERM handler is installed only in the main thread, and only when SIGTERM's previous disposition is `SIG_DFL` (`deerflow_bridge/linear_research.py:6296-6317`).
6. **Backend parser anchor, §12 (imprecise).** `forecast_inputs_from_report_markdown` spans `backend/app/utils/actors.py:2765-2831`, not 2770-2846. The mirrored regexes are at `backend/app/utils/actors.py:2686-2703`.
7. **Identity anchor, §10 and the Data table (imprecise, off by one).** The identity dict is at `deerflow_bridge/linear_research.py:3970-3972`.
8. **Control flow §1: "For v3 it sets `env["RESEARCH_ENGINE"]`" (imprecise).** `RESEARCH_ENGINE` is set for every research launch, legacy included (`backend/app/services/pipeline_orchestrator.py:2295-2301`). Only `DEERFLOW_RESEARCH_TIMEOUT` is set for v3 alone (`backend/app/services/pipeline_orchestrator.py:2302-2307`).
9. **`largest_remainder` raise condition, §11 (imprecise).** It raises only when the list is empty, no value is positive, or there are more values than `total`. An individual zero or negative value is clamped to 0 and still gets a share of at least 1 (`deerflow_bridge/linear_research.py:1366-1379`).
10. **Invariant "Unresolvable groups are removed, not published" (imprecise).** Only square and CJK-bracket groups are removed (`_STALE_CITE_GROUP_RE`, applied in QA at 5254). Non-canonical round-bracket groups such as "(S1 and S2)" or "(S1 2025)" are left as prose on purpose (`deerflow_bridge/linear_research.py:1950-1952`, `deerflow_bridge/linear_research.py:2315-2323`).
11. **§9: the `plog` owner (imprecise).** The close happens in `_dispatch_v3_engine`'s `finally`, which `main` calls (`deerflow_bridge/deerflow_research.py:16560-16561`, `deerflow_bridge/deerflow_research.py:16902-16903`).
12. **Invariant "Every missing part … recorded in `plan.fallback`" (imprecise).** Same root cause as item 2.

Nuances on confirmed items:
- **Key claim 2.** The auto-raise code sits at `deerflow_bridge/linear_research.py:739-747`, not in the cited formula lines, and is capped at the 2000 bound.
- **Surprise 12.** The exception can also be a `TypeError`, for example a list-valued weight. Because `plan.json` persists and the plan phase is already `done`, every resume hits the same exception and exits 2 (`deerflow_bridge/linear_research.py:4204`, `deerflow_bridge/linear_research.py:6353-6357`).

### Omissions (significant behaviour the map does not state)

- **The writer's preamble is dropped.** `split_writer_output` keeps text before the first `#`/`##` heading only for a single-section reply in which no heading matched. In every other reply that preamble is silently discarded (`deerflow_bridge/linear_research.py:3006`, `deerflow_bridge/linear_research.py:3050-3052`). Probe: "preamble" vanished from a two-section reply.
- **VERIFIED without any checkable number.** A finding with no 2-digit or decimal number keeps VERIFIED on the fetched flag alone, with `verified_numbers=None`. A decimal such as "5.0" canonicalises to "5" and also escapes the check (`deerflow_bridge/linear_research.py:2389-2397`, `deerflow_bridge/linear_research.py:2475`, `deerflow_bridge/linear_research.py:2715-2716`). Probe: "Growth 5.0 and 7 units [S4] (VERIFIED)" stayed VERIFIED.
- **`Plan.from_dict` leniency.**
  - Malformed KIQs are dropped one by one instead of forcing a re-plan.
  - Section `kiq_ids` are not checked against the KIQs that survive.
  - `is_scenario` is read with `bool()`, so the string "false" counts as true (`deerflow_bridge/linear_research.py:1121`, `deerflow_bridge/linear_research.py:1127-1128`).
- **Scenario frame edge cases.**
  - With more than 6 scenarios the kept frame is reordered by descending weight, so the planner's order is lost.
  - `_parse_weight` drops a minus sign in a string weight ("-20" becomes 20) (`deerflow_bridge/linear_research.py:1358`, `deerflow_bridge/linear_research.py:1415-1416`; probe).
- **Outline clamp side effects.**
  - Padding sections carry no KIQ ids.
  - The over-`smax` merge can fold a removed section's KIQs and focus into the scenario section when the removed section follows it (`deerflow_bridge/linear_research.py:1310-1318`, `deerflow_bridge/linear_research.py:1330`).
