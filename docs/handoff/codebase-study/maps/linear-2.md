# linear-2 — linear_research.py (v3 engine) part 2

Slice owned: `deerflow_bridge/linear_research.py` lines 3056–6379 (the file has 6,379 lines). I read every line of the slice. I read helpers outside the slice (part 1 of the same file, `deerflow_bridge/research_gateway.py`, `deerflow_bridge/deerflow_research.py`, `backend/app/services/research_progress.py`, `backend/app/services/pipeline_orchestrator.py`) only far enough to say what a call does. Branch `main`, checkout on disk.

**Anchor convention.** A bare `:N` or `:N–M` means `deerflow_bridge/linear_research.py:N`. Every other file is named in full, relative to the repo root.

**Scope note.** The slice is larger than its label suggests. Besides synthesis, reply trimming, QA and outputs, it holds the **whole `_Engine` class** (`:3943–5904`), including the plan, gather and gap phase drivers, and the bounded per-KIQ tool agent `KiqAgent` (`:3422–3838`). Part 1 (`:1–3055`) holds the pure building blocks these drivers call: presets, run state, plan normalisation, scenario-frame logic, citation normalisation, notes post-processing, the evidence digest and the writer-output splitter. [verifier: not all "pure" — part 1 also holds stateful/IO pieces: `_Reporter` (`:810`), `_CallTally` (`:846`), `_RunState` writing `state.json` (`:888–958`) and `_open_work_dir`, which renames a foreign `v3/` to `v3.stale-<utc>` (`:973–994`)]

---

## Purpose & position in the pipeline

`linear_research.py` is research engine **v3**, the default Stage-1 research engine. `README.md:461` says it is selected by `RESEARCH_ENGINE=v3`, by `linear`, or when the variable is unset. The backend orchestrator starts the bridge script `deerflow_bridge/deerflow_research.py` as a subprocess. When v3 is selected, the bridge's `_dispatch_v3_engine` imports this module by bare name and calls `linear_research.run(question, out_dir, args, meta, plog, write_meta, bridge=_bridge_module())` (`deerflow_bridge/deerflow_research.py:16516–16531`).

This slice holds four things:

1. **The engine driver.** `_Engine.execute` (`:4186–4200`) runs six phases in order: plan → (re-plan after an outage) → gather → gap → synthesize → qa → finalize. Each phase saves its artifacts under `out_dir/v3/` before it is marked done, so a resumed attempt skips work that already finished.
2. **The per-KIQ tool agent `KiqAgent`.** It runs an append-only `web_search`/`web_fetch` loop with hard stops and forced final notes, and falls back to deterministic notes.
3. **Synthesis and QA.** Contiguous section groups are written in parallel. A reply cut by its output cap is retried once with a wider cap, then trimmed. [verifier: not every cut reply — the group call `synth:g<n>` has no wider retry and is not trimmed; its last assigned title found is popped and rewritten alone (`:5023–5031`). The wider retry exists only in `_write_call` (single sections, exec summary, QA rewrites; `:4984–5007`), `KiqAgent._ask` (tool-call-free replies only; `:3569–3586`) and `extraction_call` (`:5687–5698`), and only when the finish reason is a truncation reason, ≥120 s remain and the budget allows (`:3588–3601`, `:4970–4982`)] Deterministic fallback sections, cross-section dedup and the executive summary follow. QA then runs deterministic checks, bounded repairs and critique rewrites, renumbers citations positionally, and builds References in code.
4. **Finalize and the boundary.** Finalize writes the contract artifacts (`sources.json`, then `research_report.md`, `actors.json`, `timeline.json`, `quantitative.json`, `contested.json`). It also calls the bridge's prediction-market, chart, quality and degradation helpers. The `run` entry point is the failure boundary: it sets signal handlers, makes `meta.status` terminal and returns exit code 0 or 2.

**There is no AI judge in v3.** "Judge/validation" here means the deterministic QA checks (`:5428–5475`), the optional critique pass (`:5385–5426`) and the bridge's `compute_research_quality`. That function is called with `judge_scorecard=None` (`:5789–5790`).

Downstream consumers:
- The bridge's `meta.json`, which `write_meta` writes.
- The orchestrator's `_surface_research_quality`, which reads `meta.research_quality` (`backend/app/services/pipeline_orchestrator.py:10564–10640`).
- The progress estimator, which parses the `research:v3:<phase>` log lines (`backend/app/services/research_progress.py:31–61`).
- The later pipeline stages, which consume the files in `handoff/`.

---

## Walkthrough (source order)

### A. Writer-reply post-processing and report assembly (`:3056–3228`)

**`drop_demoted_twins(parsed, demoted, missing)` — `:3056–3068`**
- Context: when `split_writer_output` (part 1, `:2981`) finds a heading that matches no assigned title, it demotes that heading to `###` and appends it to the previous matched section. Those demotions arrive here as `(target title, heading, block)` triples.
- For each demoted block whose heading names one of the `missing` titles, the block is deleted from `parsed[target]`. "Names" is decided by `_names_title(_section_title_key(heading), _section_title_key(title))` (`:3063–3064`). Runs of 3+ newlines are collapsed afterwards (`:3065–3066`).
- Reason: that section will be written again on its own, and the demoted copy would publish the same analysis twice.
- Returns the removed headings. It mutates `parsed` in place.

**Sentence and atom regexes — `:3075–3091`**
- `_SENTENCE_END_RE` (`:3075`) matches a terminator followed by any closing quotes/brackets and any trailing `[S<n>]` markers. The terminator is one of:
  - Latin `.!?` followed by whitespace or a closer.
  - A Latin `.!?` at the end of the string that does not follow a digit, so "at 12." may be a cut "12.5".
  - CJK `。！？`.
- `_ABBREVIATION_RE` (`:3080–3083`) matches periods that do not end a sentence: initialisms (`U.S.`, `e.g.`), single capital initials and a fixed list of short forms (Inc, Corp, Dr, month names, Gov, …). "etc." is deliberately absent.
- `_LIST_ITEM_RE` (`:3085`) matches list-item lines.
- `_CLAUSE_BREAKS` (`:3086`) is the set of clause-break characters.
- `_OPEN_BRACKET_TAIL_RE` (`:3087`) matches an unclosed bracket of up to 40 characters at the end of a string.
- `_ATOMIC_TOKEN_RE` (`:3090`) matches a number, including grouping, decimals, `%` and ranges such as `190–210` or `至`, or a short bracketed marker. A hard cut never splits one of these.

**`_sentence_ends(text)` — `:3094–3103`**
- Returns the end offsets of every `_SENTENCE_END_RE` match.
- A `.` match is skipped when `_ABBREVIATION_RE` matches within the 12 characters before it.

**`_complete_sentences(text)` — `:3106–3109`**
- Returns `text` up to its last complete-sentence end, or `""` when there is none.

**`_without_cut_item(paragraph)` — `:3112–3122`**
- Returns `None` when the paragraph does not end in a list. [verifier: it returns `None` only when NO line of the paragraph is a list item; it scans from the end for the last `_LIST_ITEM_RE` line, so a list item followed by prose continuation lines is still treated as the cut item and dropped with everything after it (`:3116–3118`)]
- Otherwise it drops the last list item and anything after it. If earlier list items remain, the intro and those items are kept. If none remain, only the intro's complete sentences are kept.

**`trim_cut_reply(text)` — `:3125–3146`**
- Purpose: the canonical trimmer for a writer reply that its output cap still cut after any retry.
- It splits the reply into paragraphs on blank lines and treats the **last paragraph as the cut one**.
  - If that paragraph ends in a list, only its last item is dropped (`_without_cut_item`).
  - If the reply has only one paragraph and it is prose, its complete sentences are kept (`:3140–3141`).
  - Otherwise the last paragraph is dropped whole, even if it holds complete sentences.
- It then pops trailing paragraphs made only of `#` lines, so no heading is left without a body (`:3144–3145`).
- Returns `""` when nothing complete is left.

**`sentence_excerpt(text, limit)` — `:3149–3178`**
- Collapses `text` to one line with `_collapse` (`:545`) and returns it unchanged if it is at most `limit` characters.
- Otherwise it tries these cuts in order:
  1. The last sentence end at or before `limit`.
  2. The first sentence, if it ends at or before `2*limit`.
  3. Scanning backwards from `limit-1` down to `0.4*limit`, a cut at a space or clause break that is not a digit-group separator (`1,234`, `12 500`) and does not leave an unclosed bracket. An `…` is appended (`:3164–3172`).
  4. A hard cut moved back to the start of any atomic token it would split, with `…` appended (`:3173–3178`).
- Used by the deterministic executive summary (`:5159`).

**`_lead_paragraph(body)` — `:3181–3187`**
- Returns the first paragraph that does not start with `#`, `|`, `- **` or a code fence.

**`section_leads(sections)` — `:3190–3193`**
- Returns `(title, lead)` for every section. The lead is hard-collapsed to `LEAD_CHARS` = 700 (`:131`).
- Note: `_collapse` (`:545–554`) is not number-safe; it cuts at a space when one falls in the last 40% of the limit.

**`report_title(question)` — `:3196–3197`**
- Returns the question collapsed to 160 characters.

**`render_report(question, language, exec_body, sections, frame)` — `:3200–3213`**
- Builds `# <title>`, then `## <Executive Summary | 执行摘要>` and the summary, then the sections in outline order.
- A non-scenario section with no non-heading line is **omitted** (`has_section_content`, `:3849`). A bare heading is never published.
- The scenario section always appears. Its body is the canonical `render_scenario_block(frame, language)` (part 1, `:1662`) followed by the writer body.
- Output ends with `\n`.

**`strip_references(report)` — `:3216–3227`**
- Cuts the report at the **last** `^## References$` line. A writer's own `### References` sub-list does not cut the report.

### B. QA helpers (`:3230–3331`)

**`remove_error_markers(body)` — `:3234–3264`**
- Removes Python tracebacks: the `Traceback (most recent call last)` line, the indented or blank continuation lines after it, and one closing `XxxError`/`Exception`/`Exit`/`Interrupt` line.
- Removes whole-line provider envelopes: `{"error": …}`, `Error code: 4xx/5xx`, `LLM request failed`, `The configured LLM provider…`.
- Returns `(text, removed_count)`.

**`cjk_ratio(text)` — `:3267–3271`**
- Removes URLs, `[S#]` markers and markdown punctuation, then returns Han characters ÷ (Han + Latin letters).
- Returns 1.0 when the text has no letters at all.

**`renumber_citations(text, known)` — `:3274–3289`**
- Assigns positional numbers `[S1..Sk]` by first appearance, only to sids where `known(sid)` is true.
- Unknown markers are replaced with `""` and spacing is tidied (`_tidy_spaces`, `:2362`).
- Returns `(text, ledger-sid order)`. That order is the order of both References and `sources.json`.

**`render_references(order, ledger_get)` — `:3292–3299`**
- Writes `## References` followed by one line per cited source: `- [S<pos>] <title≤200> — <url> (tier N; fetched|search snippet)`. The tier label comes from `rg.tier_label`.

**`report_sections(report)` — `:3302–3317`**
- Returns `(heading, body)` pairs for every `^##\s+` heading. `#` and `###` lines are not headings here.

**`citation_density(sections)` — `:3320–3331`**
- Counts paragraphs longer than 200 characters that do not start with `#` or `|`.
- Returns the share of them that carry at least one `[S#]`, together with their count. Returns `(1.0, 0)` when there are none.

### C. Bounded per-KIQ agent (`:3334–3838`)

**Module-level helpers**
- `_PROVIDER_ERRORS = (rg.ProviderUnavailable, rg.QuotaExhausted)` (`:3338`). These are the only errors that propagate out of an agent or out of optional work.
- `_MARKER_URL_RE` (`:3339`) matches a fetch target that is a marker such as `S12` or `[S12]` instead of a URL.
- `_ROW_HEADER_RE` (`:3343`) matches the `[S13] Title — domain (tier N)` row header that `ResearchTools` prints.

**`tool_output_sids(name, output)` — `:3346–3369`**
- Returns `(fetched sid | None, sids shown)`.
- For `web_fetch`, only the **first line** is read. If it is a row header, that sid counts as both fetched and shown.
- For `web_search`, every column-0 row header counts, **except** lines between `rg.UNTRUSTED_BEGIN` and `rg.UNTRUSTED_END`. This stops a page's own "[S1] …" reference list from marking ledger row 1 as shown.

**`trim_cut_notes(text)` — `:3375–3379`**
- Drops the last line of notes cut by the output cap. A finding cut mid-number must never become a fact.

**`specific_terms(text)` — `:3382–3388`**
- Returns the query terms (`rg.query_terms`) that contain a digit, plus the terms of capitalised words (treated as entities).

**`_repeats_read(terms, specific, prior)` — `:3391–3400`**
- A re-read of a page is a repeat when any of these holds:
  - `terms ⊆ prior`.
  - It names no specific term that `prior` lacks, and the Jaccard overlap is at least `READ_DUPLICATE_JACCARD` = 0.65 (`:122`).

**`_NotesCut` — `:3403–3406`**
- Raised when a reply is empty at its output cap even after the gateway's own wider retry. It maps to the retryable fallback `notes_truncated`.

**`AgentOutcome` dataclass — `:3409–3419`**
- Fields: `notes`, `fallback`, `steps`, `forced`, `fetched`, `seen`, `truncated`.

**`KiqAgent` — `:3422–3838`**

**`__init__` — `:3447–3468`**
- Stores the engine, KIQ, task, deadline and `grace` (clamped to at least 0).
- `seen` starts as the deduped seed sids. `fetched=[]`, `steps=0`, `forced=None`, `final_issue=None`, `researched=False`, `truncated=False`.
- `_reads` maps sid → list of focus-term sets. `_stored_reads=0`.
- Message classes come from `rg._msg_classes()`.

**`run()` — `:3471–3493`**
- Messages are `rg.build_messages(ENGINE_CORE, [engine.brief], task)`, i.e. `[system][RUN BRIEF][KIQ TASK]`.
- It runs `_loop`. `fallback` is then set by these rules:
  - No notes → `final_issue` or `"no_final_text"`.
  - Notes, but no finding cites a source this agent was shown (`_cites_shown_source`) → `"notes_truncated"` if `truncated`, else `"no_sourced_facts"`.
  - `_NotesCut` → `notes_truncated`.
  - `rg.ContentFiltered` → `content_filter`.
  - Any other `rg.GatewayError` → `exc.category`, for example `deadline`, `budget`, `empty`, `bad_request`, `context_too_long`.
  - Any other exception → logged warning and `error_<Type>` (`:3486–3488`).
  - **Provider errors are re-raised** (`:3478–3479`).
- Any fallback replaces the notes with `fallback_notes(reason)` (`:3489–3490`).

**`_cites_shown_source(notes)` — `:3495–3508`**
- Runs part-1 `postprocess_notes` (`:2674`) with a ledger view limited to `seen ∪ fetched` and no page-number check. Returns whether any fact survives.
- Returns True when the agent was shown nothing (nothing to fall back to).

**`_loop(messages)` — `:3510–3544`**
- At most `preset.agent_max_steps` steps (5 quick, 7 standard, 9 deep; `:616–626`).
- Each step:
  1. `_pressure` is checked first. If it returns a reason, `_force_final(reason)`.
  2. `_ask(…, label "<KID>:s<step>")`.
  3. If the reply has **no tool calls**:
     - If it is notes (`_is_notes`), return `_notes(result)`.
     - Otherwise append it. If the one nudge was already spent, `_force_final("no_notes")`. If not, mark it spent and append `NOTES_NUDGE_TEXT` (`:189`). On the last step no nudge is appended; the forced final's STOP serves as the nudge.
  4. If any tool call lacks an `id`, `_force_final("unanswerable_tool_call")` without appending the reply (`:3533–3536`).
  5. Otherwise append the AI message, run `_execute`, append the tool messages and set `researched=True`.
  6. `quiet` counts consecutive steps with nothing novel. At `NOVELTY_PATIENCE` = 2 (`:109`), `_force_final("no_new_sources")`.
- After the last step: `_force_final("step_budget")`.

**`_is_notes(text)` — `:3546–3550`**
- True when the reply has a notes heading (`has_notes_heading`, `:2551`).
- After the agent has run a tool, a cited bullet also counts (`has_notes_structure`, `:2556`).

**`_ask(messages, label)` — `:3552–3586`**
- Calls `gateway.invoke(kind="agent", tools=AGENT_TOOLS, deadline=self.deadline)`.
- `rg.EmptyResponse` with `truncated=True` → `_NotesCut`. Any other `EmptyResponse` is re-raised.
- A reply **without tool calls** that is truncated with a length/max_tokens finish reason gets one wider try (`label:wide`) at `_wider_cap(…, cap=result.output_cap)`.
  - Provider errors on that retry propagate.
  - Any other `GatewayError` keeps the cut reply and logs a warning.
- A provider-aborted reply (a finish reason that is not a truncation reason) is not widened.

**`_wider_cap(messages, cap=None)` — `:3588–3601`** (the agent version)
- `base` = `cap`, or the profile's agent cap (default 6000; `deerflow_bridge/research_gateway.py:573`).
- `wider = min(2*base, max(base, AGENT_RETRY_MAX_TOKENS=12_000))` (`:153`).
- Returns `None` when `wider ≤ base`, when the deadline has less than `TRUNCATION_RETRY_MIN_SECONDS` = 120 s left (`:154`), or when `gateway.can_spend(units(prompt) + wider*output_weight, keep_reserve=True)` fails. The agent retry may not touch the 35% budget reserve.

**`_notes(result)` — `:3603–3616`**
- Returns the text as-is when it was not truncated.
- When truncated: sets `truncated=True`, keeps `trim_cut_notes` and logs a warning. If no notes structure remains, sets `final_issue="notes_truncated"` and returns `None`.

**`_pressure(messages)` — `:3618–3626`**
- `"deadline"` if the deadline has expired or `remaining ≤ grace`.
- `"context_cap"` if `rg.estimate_tokens(messages, AGENT_TOOLS) > AGENT_CONTEXT_TOKEN_CAP` = 60,000 (`:108`).
- `"budget"` if the estimate cannot be spent while keeping the reserve.

**`_force_final(messages, reason)` — `:3628–3640`**
- Records `forced=reason` and appends `STOP_TEXT` (`:186`), then asks with label `<KID>:final`.
- Notes win, and any tool calls next to them are ignored.
- A reply with no tool calls, or with an id-less call → `_not_notes`.
- Otherwise the tool calls are answered with `TOOL_BUDGET_TEXT` (`:188`) and the agent is asked once more as `<KID>:final2`.

**`_not_notes(result)` — `:3642–3650`**
- Sets `final_issue` to `notes_truncated` (if truncated) or `unstructured_notes` (if there is text). Returns `None`.
- An empty, untruncated final leaves `final_issue=None`, so the fallback becomes `no_final_text`. [verifier: a reply with neither text nor tool calls never reaches `_not_notes` — the gateway raises `EmptyResponse` (`deerflow_bridge/research_gateway.py:1782–1784`), which `run` maps to fallback `empty` (`:3484–3485`). `no_final_text` arises when the final reply has tool calls but no text, e.g. id-less calls at `:final` or tool calls again at `:final2` (`:3634–3640`). Both are non-retryable]

**`_execute(calls)` — `:3653–3708`**
- Answers every call of one turn, in order.
- Calls with an `error`, and tools other than web_search/web_fetch, are passed to `_call_tool` (which returns an error string) and use no slot.
- Of the web calls, only the first `MAX_TOOL_CALLS_PER_STEP` = 3 (`:113`) may run. Later ones get `TOOL_CALLS_SKIPPED_TEXT`. [verifier: the slot is counted by position before screening (`:3670–3673`), so a call later refused by `_screen_read` or answered as a duplicate still uses one of the 3 slots]
- A `web_fetch` first computes focus terms, then goes through `_screen_read`, which may refuse it.
- `_repeats_in_step` dedups the same search, or the same page with a near-same focus, within the step → `DUPLICATE_CALL_TEXT`. [verifier: for a page already stored, the same-step twin is refused earlier by `_screen_read` with `ALREADY_READ_TEXT`, because `_screen_read` records the first read before the fetch runs (`:3676–3682`, `:3766–3771`); `DUPLICATE_CALL_TEXT` covers searches and not-yet-stored pages]
- Runnable calls run on a `ThreadPoolExecutor` with up to `preset.workers` threads (`thread_name_prefix="v3-tools"`). [verifier: a single runnable call runs inline without a pool (`:3688–3689`)]
- `novel` is set when a call fetches a sid not yet in `fetched`, or shows a sid not yet in `seen` (`:3694–3705`).
- Returns `(tool messages, novel)`.

**`_fetch_row(url)` — `:3710–3717`**
- Resolves an `S<n>` marker with `ledger.get` and a URL with `ledger.find`.

**`_focus_text` / `_focus_terms` — `:3719–3726`**
- The fetch's `focus` argument if it has query terms, otherwise the KIQ question.

**`_repeats_in_step(call, terms, queued)` — `:3728–3754`**
- Search key: the query whitespace-collapsed and casefolded.
- Fetch key: the canonical URL, with a marker resolved first. A repeat is decided by `_repeats_read` against the earlier focus sets of this step.

**`_screen_read(call, terms)` — `:3756–3772`**
- Applies only to pages **already stored** (`row.fetched`).
- Refuses with `ALREADY_READ_TEXT` (`:194`) when an earlier read by this agent had the same or a near-same focus.
- Refuses with `STORED_READS_EXHAUSTED_TEXT` once `MAX_STORED_READS_PER_AGENT` = 6 (`:121`) stored reads are spent.
- Otherwise counts the read and records it before the fetch runs.

**`_note_read(sid, terms)` — `:3774–3776`**
- Adds a focus-term set to `_reads[sid]` unless it is already there.

**`_call_tool(call)` — `:3778–3804`**
- `INVALID_TOOL_CALL` or `UNKNOWN_TOOL` strings for bad calls.
- `tools.search(query, agent_id=kiq.id)`.
- `tools.fetch(url, focus=…, agent_id=kiq.id, kiq_text=kiq.question)`. A marker URL is resolved to the ledger URL first.
- Any exception becomes `TOOL_ERROR(<Type>): try another source.`

**`fallback_notes(reason)` — `:3807–3838`**
- Builds deterministic notes.
- For each fetched sid, takes up to 2 `numeric_sentences` (`:2822`) of the page text after `rg.neutralize_instructions` and `rg.neutralize_citation_markers`. Sentences are scored on the KIQ terms plus the focus terms the agent read the page with. Output line: `- <title≤120>: <sentences> [S<sid>] (REPORTED)`.
- If no fetched page yields a line, it uses up to 4 seen-row snippets that contain a digit.
- Output is a full notes skeleton: `## Findings / ## Conflicts / ## Open questions` (with a line "incomplete" or "nothing_read" (`<reason>`)) `/ ## Discovered`.

### D. Deterministic section bodies and small helpers (`:3841–3932`)

- `FALLBACK_FACTS_PER_SECTION = 8` (`:3841`).
- `_fact_key(fact)` (`:3844–3846`): `(collapsed text, int sids)`.
- `has_section_content(body)` (`:3849–3851`): at least one non-blank line that is not a heading.

**`fallback_section_bodies(sections, records, language, taken=None, *, empty_when_none=False)` — `:3854–3916`**
- Builds a catalogue of every **sourced**, non-`UNVERIFIED` fact across the KIQ records, in natural KIQ order (`:3875–3885`).
- Each section's pool is the facts of the KIQs routed to it, or every fact when none is routed. Each fact is scored by the overlap between its terms and the section's title + focus terms.
- Greedy assignment repeats until no candidate is left. Each round picks the best `(overlap, −picked count, −tag rank, −outline position, −catalogue index)` among sections that have fewer than 8 picks and facts not in `taken`. `taken` is mutated (`:3894–3909`).
- Each body is `- <fact text>` lines (the `[S#]` markers are kept), sorted VERIFIED → REPORTED, then by evidence order.
- An empty body becomes `- <no_evidence>`, or `""` when `empty_when_none` is set.

**`_adopt_rewrite(section, rewrite, origin)` — `:3919–3926`**
- Sets `body` and `origin` (`repair`/`critique`), and sets or clears `trimmed`.

**`_jaccard(left, right)` — `:3929–3932`**
- Returns 0.0 when either set is empty.

### E. `_Engine` (`:3939–5904`)

Factory type aliases: `GatewayFactory` (`:3939`) and `ToolsFactory` (`:3940`). Tests inject their own.

#### E1. Construction and utilities

**`__init__` — `:3946–4018`**
- An empty question raises `_EngineFailure("empty research question")` (`:3950–3951`).
- `preset = resolve_preset(args.depth, env)` (part 1, `:698`).
- `language = detect_language(question, args.target_language)` (`:778`).
- `actor_cap = actor_cast_max(env)` (`:1425`). `actor_prompt_cap` is that cap, or `ACTOR_PROMPT_CEILING` = 60 when the cap is 0.
- The run **identity** is `{question_sha256 (whitespace-normalised), depth, model, language, engine_version "v3.0"}` (`:3970–3972`).
- `_open_work_dir` (`:973`) reuses `out_dir/v3` only when that identity matches. Otherwise it archives the dir to `v3.stale-<utc>`.
- Creates the subdirs `kiq/ sections/ gap/ extract/` (`:3976–3977`).
- `ledger = rg.SourceLedger(work/"sources_ledger.json", bridge=bridge)` (`:3978`).
- `rg.ToolLimits` uses the preset's totals and per-agent allowances, with two overrides (`:3979–3988`):
  - `planner` = (6 searches, 0 fetches).
  - `seeder` = (2 × (max_kiqs + gap_rounds × followups_per_round), 0).
- `tools = tools_factory(ledger, work/"pages", bridge, reporter, limits)` and `gateway = gateway_factory(args, reporter, bridge, preset)` (`:3989–3990`).
- **Instance monkeypatches** (`:3995–3999`):
  - `gateway.invoke` is wrapped by `_CallTally.watch` (`:846`), which counts calls as served, refused, budget or failed.
  - `tools.search` and `tools.fetch` are wrapped by `_watch_tool`.
- Run deadline: `rg.Deadline(preset.time_budget_s, self._clock, label="v3 run")` (`:4003`). The time budget is 1200 s quick, 2700 s standard, 5400 s deep, capped at 0.85 × `DEERFLOW_RESEARCH_TIMEOUT` by part 1.
- `extract_cap = max(preset.max_tokens_extract, profile json cap)` (`:4004–4005`).
- Empty state is initialised: `plan`, `brief`, `kiqs`, `records`, `synth`, `qa`, `final_report`, `_synth_context_cache`, `refused_calls`, `_outage_plan`.

**Utilities**
- `log(kind, msg)` (`:4021`): `reporter.write`. `_Reporter` (`:810`) never raises.
- `_clock()` (`:4024–4027`): returns `math.inf` once the run is cancelled, so every deadline reports zero remaining and new gateway calls fail their deadline check.
- `cancel()` (`:4029–4034`): sets the `cancelled` flag only, so a signal handler may call it.
- `_watch_tool(tool, kind)` (`:4036–4049`): once cancelled, returns `CANCELLED_TOOL_TEXT` (`:218`). It counts a search result exactly equal to `rg.MSG_SEARCH_UNAVAILABLE` as a failure.
- `units(tokens)` (`:4051–4052`): tokens × the profile's `uncached` cost weight.
- `_write_internal` (`:4054`): writes through `rg._atomic_write_text`.
- `write_text` (`:4057–4065`): writes a contract artifact. It creates the parent dir and uses `bridge._atomic_write_text` (`deerflow_bridge/deerflow_research.py:76`) when present.
- `write_json(path, obj, internal=True)` (`:4067–4072`): `ensure_ascii=False`, indent 2. Internal files use `_write_internal`; contract files use `write_text`.
- `flush_meta()` (`:4074–4078`): calls `write_meta` and swallows any error with a warning.
- `bridge_call(name, …)` (`:4080–4091`): calls an optional bridge helper. A missing helper or a raised exception is appended to `analytics_errors` (error text up to 300 characters), and the call returns `None`.
- `delimit(label, text)` (`:4093–4103`): `rg.delimit_untrusted`. An empty result still gets a wrapper containing the `no_findings` text, so the message layout stays fixed.
- `page_numbers(sid)` (`:4105–4116`): a thread-safe cache of `page_number_set(tools.page_text(sid))` (`:2493`).
- `json_call(shared, task, label, required, deadline)` (`:4118–4124`): `gateway.json`. The repair note goes only into the last message.
- `optional_allowed(tokens, deadline, keep_reserve, min_seconds=60)` (`:4126–4130`): requires `remaining ≥ min_seconds` **and** `can_spend(units(tokens) × 2)`.
- `phase(name)` contextmanager (`:4136–4149`):
  - Takes a child deadline at `PHASE_TIME_SHARE[name]` of the *remaining* run time: plan 0.12, gather 0.55, gap 0.3, synthesize 0.75, qa 0.6 (`:176–178`). **finalize has no share and uses the whole run deadline.**
  - Sets the phase to `running`, labels gateway calls with `gateway.phase(name)` and adds the elapsed seconds to `phase_seconds`.
  - It does **not** mark failures. Callers do that.
- `invalidate(phases)` (`:4151–4163`):
  - Calls `state.reset_phases`.
  - If `synthesize` is included: removes and recreates `sections/`, and deletes `digest.md`, `synth.json` and `synth_report.md`.
  - If `qa` is included: deletes `qa.json` and `qa_report.md`.
  - Logs a stage line when anything was reset.

#### E2. Lifecycle

**`announce()` — `:4166–4184`**
- Writes to `meta`: `research_engine="v3"`, `engine_version`, `depth`, `language`, `v3_workdir="v3"`, `status="running"` and `v3_preset` (17 knobs).
- Logs each preset note as a `v3 config:` warning.
- Warns when `RESEARCH_LINEAR_MODE=salvage`, which is ignored.
- Logs a resume line and flushes meta.

**`execute()` — `:4186–4200`**
- Runs announce → phase_plan → replan_after_outage → load_followups → phase_gather → phase_gap → phase_synthesize → phase_qa → `return phase_finalize()`.
- `_EngineFailure` → `meta.status="failed"`, `error`, `finished_at`, and returns **2**.

#### E3. Plan phase

**`phase_plan()` — `:4203–4232`**
- Reuse path: state `plan` is done, `plan.json` passes `Plan.from_dict` validation (`:1117`), `brief.md` exists and `_discard_outage_plan` is false. The plan is loaded and the phase returns.
- Otherwise, inside `phase("plan")`:
  1. `as_of = _utc_date()`.
  2. `render_pre_brief` (`:1511`).
  3. `_plan_calls` → `build_plan` (`:1462`), which normalises and falls back deterministically part by part.
  4. If the plan call failed because of an outage, sets `plan.fallback["model_unavailable"]=True` (`PLAN_OUTAGE_KEY`, `:207`) and `_outage_plan=True`.
  5. `render_brief` (`:1515`), then writes `plan.json` and `brief.md`, flushes the ledger and marks plan done.
- Sets `meta.plan_fallback` = the sorted fallback keys.

**`_discard_outage_plan(plan)` — `:4234–4254`**
- Applies only to an outage-template plan **and** only when no KIQ in state has facts.
- Resets the KIQs, wipes `kiq/` and `gap/`, invalidates all six phases and returns True, so the plan is made again.

**`replan_after_outage()` — `:4256–4296`**
- Runs only when *this attempt* planned during an outage and at least `REPLAN_MIN_REMAINING_SHARE` = 0.75 (`:163`) of `time_budget_s` remains.
- Reuses the scope if the scope call had succeeded.
- The deadline is a child at 0.12 of what remains. Calls are labelled with `gateway.phase("plan")`, but the engine's `phase()` is **not** used.
- `_plan_calls(single_attempt=True)`. If `raw_plan` is None, the template plan is kept.
- On success: rebuilds, persists, marks plan done "(re-planned after an outage)" and clears `_outage_plan`.

**`_plan_json(…, single_attempt)` — `:4298–4309`**
- Normal mode: `json_call`, i.e. gateway retries plus one JSON repair retry.
- Single-attempt mode: `gateway.invoke(kind="json", max_attempts=1)` and `rg.parse_json_object`. `None` raises `rg.JsonUnparseable`.

**`_plan_calls(pre_brief, deadline, scope=None, single_attempt=False)` — `:4311–4347`**
1. Scope call `plan:scope[:replan]` with `_T_SCOPE` (`:393`), requiring `scout_queries`. A `GatewayError` is logged and the result treated as no scope.
2. Scout queries: at most 6 (`_as_str_list`). If there are none, `_short_query_base(question)` (`:1148`) is used.
3. `_scout`.
4. Plan call `plan:plan[:replan]` with `_T_PLAN` (`:403`), requiring `kiqs`, `sections` and `scenarios`. The shared context is `[pre_brief, delimit("scout search results", digest)]`.
- `outage` is True only when the plan call raised `ProviderUnavailable`, `QuotaExhausted` or `DeadlineExceeded` (`:4343`).
- Returns `(scope with the effective scout_queries, raw_plan, outage)`.

**`_scout(queries)` — `:4349–4361`**
- Runs `gateway.fan_out` of `tools.search(q, agent_id="planner")` with `warm_first=False`.
- Digest blocks are `Query: <q>\n<result>`, capped at `SCOUT_DIGEST_CHARS` = 6000 and cut at a line boundary. Empty → `(no scout results)`.

**`load_followups()` — `:4363–4376`**
- For each round 1..gap_rounds, loads `gap/round<n>.json` and appends its follow-up `Kiq`s, unless the round's verdict is `complete`. This only matters on resume.

#### E4. Gather phase

**`_load_records(kiqs, retry_cut_short=False)` — `:4379–4394`**
- Adopts `kiq/<id>.json` for a KIQ whose state is `done` when the file's `id` matches and `facts` is a list.
- With `retry_cut_short`, KIQs whose state fallback is in `_RETRYABLE_FALLBACKS` = {deadline, budget, unstructured_notes, no_sourced_facts, notes_truncated, provider} (`:214–215`) stay pending.

**`phase_gather()` — `:4396–4459`**
- `retry = resumed and not synthesize done`. Plan KIQs (round 0) and follow-ups (round > 0) are loaded separately. Follow-ups are retried only if gap is not done either.
- Nothing pending → marks gather done if needed and returns.
- Inside `phase("gather")`:
  1. `gather_kiqs`.
  2. If any KIQ completed, invalidates synthesize, qa and finalize.
  3. Reloads plan records, so a retry that did not finish keeps its earlier notes.
  4. Flushes the ledger.
- Decision rules (`:4432–4458`):
  - Provider error **and** 0 facts → gather `failed` and `_EngineFailure("provider_unavailable: gather failed with no evidence …")`.
  - 0 facts and no provider error → `_fail_without_evidence()`.
  - `written` = plan KIQs with a record and no `stats.fallback`. Provider error **and** `2·written < len(plan_kiqs)` → `failed` and `_EngineFailure("provider_unavailable: gather researched only …")`.
  - Provider error otherwise → gather `partial`, with a detail listing the missing and stubbed KIQs. A warning is logged and the run continues to synthesis.
  - Otherwise → `done`.

**`_tool_failures()` — `:4461–4469`**
- `search_failed` is the engine's own count.
- `fetch_failed = tools.failures − search_failed`.
- `searches`/`fetches` are the larger of the tool stats and the failure counts.

**`_fail_without_evidence()` — `:4471–4483`**
- Resets the KIQs in state and clears `records`.
- Marks gather `failed` with "no sourced evidence (<n of m searches and k of j fetches failed>)" and raises `_EngineFailure("evidence_unavailable: …")`.

**`gather_kiqs(kiqs, deadline)` — `:4485–4509`**
- Logs `research:v3:gather start (<n> KIQs, workers=<w>)`. The progress estimator reads this line.
- `_run_seeds`.
- If there are at least 2 KIQs, `gateway.prime([ENGINE_CORE][brief] PRIME_TASK, kind="agent", tools=AGENT_TOOLS)` warms the cache.
- `grace = _final_notes_grace(deadline)`.
- One `_gather_job` per KIQ through `gateway.fan_out(warm_first=False, workers=preset.workers)`.
- The first provider error is kept. Other exceptions are logged.
- Returns `{completed: KIQs with a record, provider_error}`.

**`_final_notes_grace(deadline)` — `:4511–4521`**
- `min(max(FINAL_NOTES_GRACE_S=90, agent timeout (default 240)), FINAL_NOTES_GRACE_SHARE=0.25 × deadline.remaining())`.

**`_gather_job(…)` — `:4523–4548`**
- Returns `"skipped"` when `abort` is set or the run is cancelled.
- On a provider error: sets `abort` so no new KIQs start. If the agent had fetched pages and the run is not cancelled, persists `fallback_notes("provider")` (a retryable fallback), then re-raises.
- Cancelled after the agent ran → returns `"cancelled"` without persisting.
- Otherwise `_finish_kiq` → `"done"`.

**`_finish_kiq(kiq, outcome)` — `:4550–4586`**
- Runs `postprocess_notes` with a ledger view **limited to sources the agent was shown** (`seen ∪ fetched`) and `self.page_numbers` for the VERIFIED check.
- Record fields: `id, question, kind, round, facts, unsourced, conflicts, open_questions, discovered, sources (sorted cited sids), stats{steps, forced, fallback, truncated, fetched(list), seen(count), tools(per-agent stats)}, finished_at`.
- Order: flush the ledger → write `kiq/<id>.md` → write `kiq/<id>.json` → `state.mark_kiq(done, facts, verified, fallback)` → store the record in memory under the lock.
- Logs `[ok] research:v3:gather <KID> facts=… verified=… sources=…[ fallback=…]`. The progress estimator counts this as a unit completion.

**`_run_seeds(kiqs)` — `:4588–4615`**
- Takes up to 2 queries per KIQ, dedups them run-wide by whitespace-collapsed casefold, and runs them concurrently as `agent_id="seeder"`.
- Each KIQ's seed rows are the shown sids, sorted by tier (S1 < S2 < S3 < other), then by order of appearance, and capped at `SEED_ROWS_PER_KIQ` = 6.

**`_kiq_task(kiq, seed_rows)` — `:4617–4634`**
- Seed lines are `[S<sid>] title — domain (tier N)`, the URL, and a snippet of up to 200 characters. They are wrapped by `rg.delimit_untrusted("seed search results")`.
- Rendered with `_T_KIQ_TASK` (`:416`): KIQ id and question, why, emphasis by kind (`_KIND_EMPHASIS`, `:511`), the seeds or "(no seed results; start with web_search)", the search/fetch/step allowances and the language.

#### E5. Gap phase

**`phase_gap()` — `:4637–4670`**
- Skips (reloading every record) when gap is `done`, or `partial` while synthesize is done.
- Preset disables gap (gap_rounds ≤ 0 or followups_per_round ≤ 0) → `done` "disabled by preset". This is the quick preset.
- Inside `phase("gap")`, runs rounds until one returns a stop reason.
  - A stop reason starting with `"provider failure"` (`GAP_PROVIDER_STOP`, `:141`) → status `partial`.
  - Any exception is caught, with status `partial` if it was a provider error. The run continues to synthesis.
- Reloads follow-up records, flushes the ledger and sets the phase status.

**`_followup_capacity()` — `:4672–4679`**
- `min(remaining searches // 3, remaining fetches // 1)`. `GAP_MIN_SEARCHES_PER_FOLLOWUP` = 2 seed queries + 1 (`:145`).

**`_gap_round(round_no, deadline)` — `:4681–4732`**
1. Gate: `optional_allowed(estimate(brief) + 4000, keep_reserve=True, min_seconds=120)`. Otherwise returns `"budget_or_deadline"`.
2. Capacity ≤ 0 → `"tool budget exhausted (…)"`.
3. Logs `research:v3:gap round <n>`.
4. Reuses `gap/round<n>.json` if it is valid. Otherwise runs `_gap_review(max_followups=min(followups_per_round, capacity))` and persists `{round, verdict, follow_ups, rejected, created_at}`.
5. Verdict `complete` or no follow-ups → `"evidence judged complete"`.
6. Adds the new follow-ups to `kiqs`, loads their records (with the retry-cut-short rule) and trims the pending list to `capacity`.
7. `gather_kiqs`. Invalidates synthesize, qa and finalize if any completed. A provider error → `"provider failure (<Type>)"`.
8. Fewer than `GAP_MIN_NEW_VERIFIED` = 3 new VERIFIED facts → `"diminishing returns (…)"`. Otherwise `None`, and the next round runs.

**`_gap_review(round_no, deadline, max_followups)` — `:4734–4767`**
- `json_call([brief], _T_GAP)` (`:435`) with the coverage matrix and the list of KIQs already investigated. Requires `follow_ups`.
- Each item (a string or a dict) gives a question collapsed to 400 characters. Items are rejected as `"near-duplicate of an existing KIQ"` when their Jaccard with any existing or accepted question is at least `GAP_DUPLICATE_JACCARD` = 0.6, and as `"over the per-round cap"` beyond the cap.
- Accepted follow-ups get id `G<round>F<n>`, up to 3 queries (each cut to `rg.MAX_QUERY_CHARS`=300; default: the question's first 200 characters), `kind="general"` and `round=round_no`.

**`_coverage_matrix()` — `:4769–4783`**
- One line per KIQ: "not researched", or facts/verified/sources counts, the first 3 open questions and the first 3 discovered leads.

#### E6. Synthesize phase

**`synth_context()` — `:4787–4803`**
- Reads `digest.md`. If it is missing, builds it with `build_digest(records in KIQ order, ledger.get, preset.digest_cap, language)` (`:2896`) and records `meta.digest_dropped_lines`.
- The result is cached as `delimit("research evidence", raw)`. These bytes are identical for every writer, repair and resume, so they are the shared cached prefix.

**`phase_synthesize()` — `:4808–4877`**
- Reuse: synthesize is done and `_load_synth()` is valid → `meta.truncated_sections` is set and the phase returns.
- Inside `phase("synthesize")`:
  1. Resets the context cache and builds the context.
  2. `bodies = _load_section_files()` reuses persisted sections.
  3. `_groups` over the sections not yet written. Logs `research:v3:synthesize start (<n> groups)`.
  4. Primes with `[brief, context]` if there are at least 2 groups.
  5. Fans out `_write_group`. The first provider error is kept; other errors are logged; results are merged into `bodies`.
  6. Then, inside a `try`:
     - A provider error is re-raised.
     - `fallback_section_bodies` for the sections without a body (in outline order, so deterministic sections never share a finding).
     - Section dicts `{index, title, is_scenario, body, origin: writer|fallback}`.
     - `_dedup` (bridge) → `meta.cross_section_duplicates_removed`.
     - `_refill_emptied` → `meta.synthesis_dropped_sections`.
     - Sets `trimmed` on writer sections that have a `.trimmed` marker.
     - `_exec_summary`.
  7. A provider error from any of this → synthesize `failed` and `_EngineFailure("provider_unavailable: synthesis failed …")`.
  8. Persists `synth.json` and `synth_report.md` (`render_report`), invalidates qa and finalize, and marks synthesize done with "<n> fallback sections".
- Sets `meta.synthesis_fallback_sections`, `meta.executive_summary_origin` and `meta.truncated_sections`.

**`_trimmed_titles(exec_trimmed, sections)` — `:4879–4883`**
- The exec-summary title first, if it was trimmed, then the titles of trimmed sections.

**`_load_synth()` — `:4885–4895`**
- Valid only if `exec_summary` is a str and the section titles equal the plan titles in order.

**`_load_section_files()` — `:4897–4903`**
- Reads `sections/NN.md` for the plan sections. Each needs at least `WRITER_BODY_MIN_CHARS` = 80 characters (`:130`).

**`_groups(sections)` — `:4905–4917`**
- `count = max(ceil(n/3), min(2·workers, n))`, then contiguous groups as even as possible. With 4 workers and 12 sections that is 8 groups of 1 or 2 sections.

**`_section_target()` — `:4919–4921`**
- `per = max(150, (target_units − 450)/n_sections)`. The target text is "about <per> words", or "about <1.8·per> Chinese characters".

**`section_task(sections, note="", current="")` — `:4923–4945`**
- The volatile last message. It contains: "SECTION WRITING TASK"; the exact `## <title>` heading lines, each with target length, focus and primary-evidence KIQs; `_SCENARIO_SECTION_NOTE` (`:505`) for the scenario section; `_SECTION_RULES` (`:494`); an optional "Current version …" block; and an optional note.

**`clean_body(body, section)` — `:4947–4954`**
- In the scenario section, removes any `###` heading that equals the localised "Scenario Probability Distribution", because the engine inserts its own block.

**`_persist_section(index, body, trimmed=False)` — `:4956–4965`**
- Writes `sections/NN.md`. Index 0 is the executive summary. Creates or removes the `NN.trimmed` marker.

**`_section_trimmed(index)` — `:4967–4968`**
- True when the `NN.trimmed` marker exists.

**`_wider_cap(kind, messages, deadline, *, ceiling, cap=None)` — `:4970–4982`** (the engine version)
- Same formula as the agent version, but the ceiling is passed in and the budget check uses `keep_reserve=False`.

**`_write_call(messages, label, deadline)` — `:4984–5007`**
- A `kind="write"` invoke.
- A truncated reply with a truncation finish reason gets one `label:wide` retry, up to `WRITER_RETRY_MAX_TOKENS` = 32,000 (`:151`).
- Provider errors propagate. Any other `GatewayError` keeps the cut reply.
- The result may still be truncated, so callers trim it.

**`_trim_cut(body, what)` — `:5009–5014`**
- `trim_cut_reply` plus a warning that gives the kept and original lengths.

**`_write_group(number, group, context, deadline)` — `:5016–5062`**
- One `gateway.invoke(kind="write", label="synth:g<n>")` call. **This call has no wider retry.**
- `split_writer_output(text, titles, demoted)`.
- If the reply is truncated, the last assigned title found in `parsed` (in outline order) is popped (`:5028–5031`).
- Sections whose cleaned body is under 80 characters are "missing". Demoted twins of missing sections are dropped.
- Usable bodies are persisted.
- On a `GatewayError` (other than a provider error, which propagates): logs a warning. `retry` is set False for `BudgetExhausted` or `DeadlineExceeded`.
- Every unwritten section → `_write_single`, sequentially and only if `retry`. Otherwise it goes to fallback.
- Logs `[ok] research:v3:synthesize G<n> written=… fallback=…`. The progress estimator counts this as a unit.

**`_write_single(section, context, deadline)` — `:5064–5080`**
- A one-section task with the note *"Your previous reply did not contain a usable '## <title>' section."*
- Uses `_write_call` (`synth:s<i>`). A truncated reply is trimmed.
- Returns `(body, truncated)` if the body is at least 80 characters, else `None`.

**`_fallback_section(section)` — `:5082–5085`**
- Single-section wrapper around `fallback_section_bodies`. **No production caller.** Only `backend/tests/test_research_engine_v3_text.py:148` uses it.

**`_refill_emptied(sections)` — `:5087–5112`**
- `taken` = facts whose text already appears in any section body.
- Each non-scenario, non-dropped section left without content gets `fallback_section_bodies([outline], …, taken, empty_when_none=True)`. That gives origin `fallback`, or origin `dropped` with an empty body, in which case the title is returned.

**`_dedup(sections, rewrites_last=False)` — `:5114–5128`**
- Calls the bridge's `dedup_cross_section_paragraphs(texts)` (`deerflow_bridge/deerflow_research.py:5960`). That function removes any paragraph whose 12-shingle overlap with earlier sections is at least 0.75.
- With `rewrites_last`, sections with origin `repair`/`critique` are processed last, so the original copy survives.
- An unexpected shape from the bridge → nothing changes and it returns 0. The executive summary is **not** deduped.

**`_exec_summary(sections, deadline)` — `:5130–5163`**
- Reuses `sections/00.md` if it is at least 80 characters.
- Otherwise builds a "SECTION LEADS" block (section number, title, lead) and calls `_write_call(… _T_EXEC …)` (`:445`, label `synth:exec`). The target is 300–600 words, or 500–1000 Chinese characters.
- Takes the body under the exact heading and trims it if truncated. At least 80 characters → persists `00.md` (plus a trimmed marker if needed) and returns `"writer"`.
- Provider errors propagate. Any other failure or an unusable reply → a deterministic summary: `- <title>: sentence_excerpt(full lead paragraph, 300)` per section, followed by `<Scenario frame>: name w%; …`. Origin `"fallback"`.

#### E7. QA phase

**`phase_qa()` — `:5166–5187`**
- Reuse: requires `qa.json` with a list `citation_order` and a non-empty `qa_report.md`.
- Otherwise `_run_qa` inside `phase("qa")`, which persists `qa.json` and `qa_report.md` and marks qa done with `passed=<bool>`.
- Sets `meta.research_qa` (`_qa_meta`: `passed, failures, repaired, checks`) and `meta.truncated_sections`.
- Logs `[ok] research:v3:qa passed=… failures=… repaired=…`.

**`_run_qa(deadline)` — `:5194–5270`**, in order:
1. Copies the synth sections and runs `remove_error_markers` on the summary and every section → repaired entry `no_error_markers`.
2. `_repairs` (at most 3 rewrites).
3. If `preset.critique` (deep only by default; `:628`): `_critique`. Provider errors are caught and logged.
4. `_dedup(rewrites_last=True)`. If anything was removed → repaired entry and `_refill_emptied`.
5. `fix_scenario_weights` (`:1786`) on the summary and each section → repaired entry with per-section fixes.
6. `strip_extra_scenario_probabilities` (`:1886`) on the summary and on scenario sections or sections whose title matches `_SCENARIO_CUE_RE`. This removes probabilities given to scenarios outside the frame.
7. `render_report`. If `parse_report_scenarios(report)` does not match the frame, `neutralize_scenario_markup` runs on every body and the report is rendered again.
8. `scenario_ok`.
9. `citable = _citable_sids()`. Then `normalize_citations` → `strip_stale_citations`, which records unresolved groups (the first 20) → `renumber_citations` with `known = sid ∈ citable and in the ledger` → append `render_references(order)`.
10. `trimmed` titles and `dropped` titles (non-scenario sections with no content). `_qa_checks`.
- `qa` = `{passed, checks, failures, repaired, critique_issues, truncated_sections, dropped_sections, citation_order, report_chars, report_sha256, created_at}`. Returns `(qa, final)`.

**`_citable_sids()` — `:5272–5282`**
- The `[S#]` markers in `digest.md` (its SOURCE INDEX) plus every fact's sids across the records.

**`_repairs(sections, context, deadline)` — `:5284–5304`**
- Candidates: sections with origin `fallback`, then other sections whose stripped body is under `SECTION_MIN_CHARS` = 200. Sections without content sort first.
- The first `MAX_REPAIRS` = 3 are rewritten through `_parallel_rewrites`, with the problem text "list of raw notes" or "too short (N characters)" and label `qa:repair:<i>`.
- An adopted rewrite gets origin `repair` and a repaired entry `section_length`.

**`_parallel_rewrites(jobs, context, deadline, what)` — `:5306–5343`**
- Pops jobs from the end until `optional_allowed(sum of prompt tokens, keep_reserve=False)` passes. Popped jobs count as skipped and return `None`.
- Primes `qa:prime` if there are at least 2 jobs, then fans out `_rewrite_section`.
- Provider-error results → `None`. Other exception results are **re-raised**.
- Results come back in input order, followed by `None` for each skipped job.

**`_rewrite_messages` — `:5345–5348`**
- The writer layout with `note="Problem to fix: …"` and `current=<old body>`.

**`_rewrite_section(section, context, deadline, problem, label)` — `:5350–5383`**
- Has its own `optional_allowed` gate, then `_write_call`.
- If the reply is truncated:
  - Rejected when the section is complete (origin is not `fallback` and it is not trimmed).
  - Otherwise trimmed.
- Adopted only if the body is at least 200 characters **and**, when the old body had citations, the new body keeps at least `CITATION_KEEP_RATIO` = 0.8 of them (`:136`).
- Returns `(body, truncated)` or `None`.

**`_critique(exec_body, sections, context, deadline)` — `:5385–5426`**
- Renders the report and calls `json_call([brief, delimit("research report", report)], _T_CRITIQUE)` (`:451`), label `qa:critique`. Gated on `optional_allowed(min_seconds=180)`.
- Issues: up to `MAX_CRITIQUE_ISSUES` = 5. Each section title is fuzzy-matched with `_match_title` (`:2954`, ratio ≥ 0.8).
- At most `MAX_CRITIQUE_REWRITES` = 3 sections, one rewrite each, carrying all of that section's issues. Label `qa:critique:<i>`.
- An adopted rewrite gets origin `critique` and one repaired entry per issue.
- Non-provider gateway errors → `([], [])`.

**`_qa_checks(final, scenario_ok, trimmed, dropped)` — `:5428–5475`**

| check | passes when | anchor |
|---|---|---|
| `sections_in_order` | `##` headings equal [exec title] + the plan titles not dropped + ["References"] | `:5447` |
| `section_min_length` | every non-References `##` body is ≥ 200 characters (the detail string hardcodes "200") | `:5450` |
| `citation_density` | ≥ 0.5 of paragraphs over 200 characters carry a citation | `:5452` |
| `scenario_block` | the report parses to the canonical frame | `:5454` |
| `scenario_weights_consistent` | `fix_scenario_weights` on the prose finds nothing to fix **and** `scenario_weight_conflicts` is empty | `:5457` |
| `no_stale_citations` | `stale_citation_tokens(prose)` is empty | `:5461` |
| `no_dropped_sections` | no section was omitted | `:5464` |
| `no_error_markers` | `remove_error_markers(final)` removed 0 lines | `:5467` |
| `complete_sections` | no section was trimmed | `:5468` |
| `language` (Chinese only) | `cjk_ratio(prose) ≥ 0.3` | `:5472–5474` |

**QA failures never block publication.** `passed` is only recorded.

#### E8. Finalize phase

**`_filename(attr, default)` — `:5478–5480`**
- Uses the bridge's `REPORT_FILENAME` etc. (`deerflow_bridge/deerflow_research.py:861–873`) when present.

**`_model_answered()` — `:5482–5496`**
- True when any of these holds: this attempt had at least one served call; the plan is not a `plan` fallback; any KIQ record has no fallback; the summary or any section came from a writer; any QA repair was adopted.

**`_require_model_output()` — `:5498–5524`**
- Returns if the model answered.
- If calls were refused by the content filter (this attempt, or KIQs with `content_filter` fallbacks): sets `refused_calls` and publishes. This later becomes a degradation event.
- If no call `failed`: publishes. This covers, for example, a run whose calls were all refused by the budget.
- Otherwise: resets the KIQs, clears `records`, invalidates gather, gap, synthesize and qa, marks finalize `failed` "no model output" and raises `_EngineFailure("provider_unavailable: no model output (<n> model call(s) failed and none was answered)")`.

**`phase_finalize()` — `:5526–5568`**
1. Logs `research:v3:finalize start`, then `_require_model_output()` (outside `phase()`).
2. Inside `phase("finalize")`, which uses the whole run deadline:
   - The report must be at least `MIN_REPORT_CHARS` = 400 stripped characters. Otherwise finalize `failed` and `_EngineFailure("report_too_short: …")`.
   - **`sources.json` is written first, then `research_report.md`** (`:5538–5542`).
   - `_structured(strip_references(report))` → `_write_structured` → `_analytics`.
   - `bridge._collect_prediction_markets(out_dir, question, report, meta, reporter, model_name=…)`.
   - `bridge._render_research_charts(out_dir, meta, reporter, question=…)`.
   - Re-reads `research_report.md`, because the market helper may have appended a section (`deerflow_bridge/deerflow_research.py:15715`).
   - `bridge.count_prose_words`.
   - Sets meta: the counts, `report_chars`, `sources_count`, `fetched_sources_count`, `as_of_date` and `report_words` (if an int).
   - Finalize `done`.
3. `meta.status="completed"`, `finished_at`, and `error` is popped. Logs `[done] research complete (v3: …)` and **returns 0**.
- There is **no resume skip** for finalize. Every attempt that reaches it rewrites all contract files and calls the market and chart helpers again. Extraction is memoised (see `_structured`).

**`_source_id(url)` — `:5570–5579`**
- `bridge.stable_source_id(url)` (`deerflow_bridge/deerflow_research.py:1348`), else `"src_" + sha256(canonical_url)[:16]`.

**`_source_rows(order)` — `:5581–5603`**
- One `sources.json` row per cited sid, in positional order: `{source_id, url, title, tier, date: None, source_origin: "fetched"|"cited", reachable: True|None, [content_sha256, excerpt (≤ EXCERPT_CHARS=1200)] if fetched, supports: [], independent: None}`.

**`_structured(report_body, deadline)` — `:5605–5653`**
- For `actors` and `facts`, reuses `extract/<kind>.json` when its `report_sha256` equals the sha256 of the report body (without References).
- `--no-actors` (`args.no_actors`) skips the actors extraction.
- The rest run in parallel. Prime `extract:prime` if both are needed. `extraction_call` with `_T_ACTORS` (`:457`, requires `actors`) or `_T_FACTS` (`:470`, requires `quantitative_facts`).
- A failure is logged and the deterministic fallback is used.
- Successes are memoised with `{report_sha256, result, truncated}`.
- Truncated kinds → `meta.<kind>_truncated=True` and a warning.

**`extraction_call(shared, task, label, required, deadline)` — `:5655–5707`**
- Runs at `extract_cap`.
- A reply cut by its cap → one wider retry (`label:wide`) up to `EXTRACT_RETRY_MAX_TOKENS` = 64,000, using the engine `_wider_cap`. **Any `GatewayError` on that retry, including provider errors, keeps the cut reply.**
- A complete but unparseable reply → one repair retry (`label:retry1`) with `rg._json_retry_note`.
- `EmptyResponse` with `truncated` → `JsonUnparseable` (no retry). A non-truncated `EmptyResponse` → treated as empty text.
- Still unparseable → `rg.JsonUnparseable`.
- Returns `(object, truncated)`. Truncated objects come from the gateway's truncation repair inside `parse_json_object`.

**`_write_structured(actors_raw, facts_raw, sources)` — `:5709–5776`**
- **Always writes all four files**, even when they are empty, so no stale file from an earlier attempt survives.
- `--no-actors` → `meta.actors_skipped`.
- Actors: `normalize_actor_rows(…, 0)` (uncapped). If that is empty and actors were not skipped, falls back to the planner's actors (`role` = `why`) and sets `meta.actors_degraded`.
- `facts_raw is None` → `meta.structured_facts_degraded`.
- Builds `timeline`, `quant` and `contested` through the normalisers.
- `obj` = `{central_question (≤600, else restated question, else question), as_of_date (YYYY-MM-DD, else plan.as_of), situation_brief, actors, relationships, hot_topics (≤12)}`.
- `bridge.enforce_actor_cast(obj, meta, reporter)` applies a ranked cut. If the cut did not run and the cap is still exceeded, the first `actor_cap` actors are kept and relationships are re-normalised (`:5741–5744`).
- `bridge.enrich_quantitative_rows`.
- `bridge.annotate_recency_rows` on quant (`as_of_date`) and on the timeline (`date`). It annotates in place, with `stale_days` = `RESEARCH_STALE_DAYS` or 365. Results go to `meta.quant_freshness` and `meta.timeline_freshness`.
- `obj` also gets `key_events`, `quantitative_facts`, `contested_claims` and `forecast_inputs`. The keys `sources` and `actor_intelligence_contract` are removed, as is each actor's `intelligence`, so the rows stay unsealed legacy rows.
- Writes `actors.json` (obj), `timeline.json`, `quantitative.json` and `contested.json` through `write_text`.
- Returns the counts plus `_actors_obj`.

**`forecast_inputs()` — `:5778–5781`**
- `{scenarios: [{name, probability: weight/100 (4 dp), narrative: thesis}], base_rates: [], drivers: [], indicators: []}`.

**`_analytics(sources, actors_obj)` — `:5783–5800`**
- `bridge.source_tier_histogram` → `meta.source_tiers`.
- `grounding` = fetched ÷ cited sources, rounded to 3 dp.
- `bridge.compute_research_quality(sources, actors_obj, judge_scorecard=None, grounding=…)`. If it returns a dict, the degradation events are folded in (`degraded=True`, `degradation` deduped and appended) and the result goes to `meta.research_quality`.

**`_research_events()` — `:5802–5847`**
- Template plan from an outage; otherwise a `plan` fallback; otherwise a `kiqs` or `scenarios` fallback.
- Content-filter refusals.
- Missing planned or follow-up KIQs.
- KIQs that ended in deterministic notes (with their reasons).
- Gap `partial`, or a gap detail starting with `stopped:`.
- Search failures ≥ 20% (`5·failed ≥ searches`).
- Fetch failures ≥ 50%.

**`_degradation_events(actor_count)` — `:5849–5879`**
- The research events, plus: trimmed sections; synth-time fallback sections that QA did not rewrite; dropped sections; a fallback executive summary; truncated extractions; actor extraction failures (wording depends on whether any actors were published); a fact extraction failure.

#### E9. Telemetry

**`attach_telemetry()` — `:5882–5904`**
- Called on every exit from `run`'s `finally`.
- Writes `v3/usage.json` (`gateway.ledger.to_dict()`). An `OSError` is only a warning.
- Sets `meta.usage` (`total, phases, calls_recorded, calls_dropped`), `meta.tools` (tool stats) and `meta.phases` (each state phase plus `seconds`).
- Sets `meta.kiqs` (`planned, followups, completed, fallback, facts, verified`) and `meta.analytics_errors` when non-empty.

### F. Structured-output normalisers (`:5907–6127`)

These tolerate any JSON shape the model returns.

- Enumerations: `_INFLUENCE`, `_ROLE_CLASSES`, `_RELATION_TYPES` (16 edge types incl. `OTHER`), `_VALENCES`, `_VALUE_TYPES` (`:5911–5917`).
- `_parse_iso_date` (`:5920`): reads the first 10 characters.
- `_positive_int(value, default)` (`:5927`): returns the default for anything that is not a positive number.
- `_number_in(value, low, high)` (`:5935`): clamps; returns `None` for bools, non-numbers or non-finite values.

**`normalize_actor_rows(value, cap)` — `:5945–6001`**
- Dedups actors by `_name_key` (`:563`). The type is mapped through `_ACTOR_TYPES` (`:1003`), defaulting to `Other`.
- Text fields (≤ 1200): `role, stance, description, stated_vs_revealed, memory`.
- `influence` defaults to `medium`. `simulation_tier` is clamped to 1–4 (default 2). `role_class` is kept only if valid.
- List fields (≤ 12 × 300): `aliases, goals, constraints, assets, vulnerabilities`.
- Up to 8 `incentives` that have a `driver`. `worldview` keeps values, beliefs, identity and frame. `risk_tolerance` is kept only if valid.
- `salience`: tier 1–4, defaulting to `simulation_tier`; score 0–1, default 0.5; basis.
- `cap ≤ 0` means no cap. The engine always passes 0.

**`normalize_relationships(value, actors)` — `:6004–6043`**
- Both endpoints must resolve to cast names or aliases, and self-edges are dropped.
- The type is uppercased with spaces turned into `_`; anything not allowed becomes `OTHER`. Edges are deduped on `(source, target, type)`.
- Optional fields: `relation_label/since/until/basis` (≤ 400), a valid `valence`, `polarity` (−1..1), `strength` (0..1), `sign` (`+`/`-`).

**`normalize_situation` — `:6046–6052`**
- Three text fields (≤ 1500), plus `fault_lines` and `catalysts` (≤ 10 each). Returns `{}` when everything is empty.

**`normalize_events` — `:6055–6065`**
- `{date ≤ 40, event ≤ 600}`. Both are required. At most `MAX_TIMELINE_ROWS` = 40.

**`_source_for_ref(ref, sources)` — `:6068–6073`**
- Takes the first digit run of the ref (`"S3"` → 3) as a 1-based position in `sources.json`.

**`normalize_quant(value, sources)` — `:6076–6103`**
- Requires `metric` and a non-empty `value`. A numeric value is kept as a number; anything else becomes a string of up to 80 characters.
- Optional text fields; a valid `value_type`.
- `source_ref` resolves `source_url` and `tier`, and fills `source` with the title if it is missing.
- At most `MAX_QUANT_ROWS` = 60.

**`normalize_contested(value, sources)` — `:6106–6127`**
- Requires a `claim`. Each position needs a `stance`. Position `sources` refs become URLs, or the raw ref when they cannot be resolved. The position tier is the lowest-sorting tier.
- `status` is one of contested, resolved or single-origin (default contested). Includes `why_they_differ`.
- At most `MAX_CONTESTED_ROWS` = 15.

### G. Production factories and the model lease (`:6130–6279`)

- `LEASE_WAIT_ENV="RESEARCH_MODEL_LEASE_WAIT_SECONDS"`, `LEASE_WAIT_CAP_S=300`, `LEASE_WAIT_STEP_S=30` (`:6141–6143`).

**`_cap_lease_wait(env)` — `:6146–6161`**
- If the variable is unset, not an integer, or greater than 300, it is **written** as `"300"`.
- Returns the capped wait (at least 1).

**`_lease_wait(ceiling, deadline)` — `:6164–6175`**
- With no deadline, returns `ceiling`.
- Otherwise `spare = deadline.remaining() − rg.MIN_CALL_SECONDS (30)`. Returns `ceiling` if `spare ≥ ceiling`, 1 if `spare < 30`, else `spare` rounded down to a multiple of 30.

**`_bridge_lease(bridge, reporter, env=None)` — `:6178–6234`**
- Returns `None` when `bridge._model_call_lease` is missing.
- Otherwise returns a `lease(deadline=None)` contextmanager:
  - A process-local `turn` lock makes this process's lease acquisitions take turns. It waits up to `_lease_wait`.
  - Before acquiring, the env variable is rewritten to that wait.
  - `lease_fn(1)` is entered on an `ExitStack`.
  - A `TimeoutError` (capacity), or failing to get the turn in time, **ends leasing for the rest of the run**. The `ended` lock is acquired permanently and one warning is written.
  - Any other exception → one warning, and the call proceeds without a lease.
- The gateway passes each call's deadline because the factory accepts a `deadline` keyword (`deerflow_bridge/research_gateway.py:1440`, `:1607–1612`).
- `bridge._model_call_lease` is `deerflow_bridge/deerflow_research.py:4549–4552`, which delegates to `research_budget.model_call_lease`. That function reads the wait from the environment (`deerflow_bridge/research_budget.py:925–929`).

**`_deerflow_app_config(args)` — `:6237–6252`**
- If `--config` is given: `AppConfig.from_file(path)` + `set_app_config(config)`, a process-wide side effect. A bad file raises.

**`_default_gateway_factory(args, plog, bridge, preset)` — `:6255–6273`**
- Lazily imports `deerflow.models.create_chat_model` and builds the primary model with `thinking_enabled=False`.
- An optional fallback model comes from `os.environ["DEERFLOW_FALLBACK_MODEL"]` when it differs from the primary. If that fails, a warning is logged and the run continues without it.
- Returns `rg.ModelGateway(model, reporter, fallback_model, lease=_bridge_lease(bridge, reporter), max_concurrency=preset.workers, budget_units=preset.budget_units, reserve_share=0.35)`.

**`_default_tools_factory` — `:6276–6279`**
- `rg.ResearchTools(ledger, pages_dir, bridge=bridge, plog=plog, limits=limits)`.

### H. Entry point (`:6282–6379`)

**`_stop_on_signals(engine)` — `:6286–6323`**
- Does nothing outside the main thread.
- SIGINT is taken over only if its current handler is a Python callable. The new handler calls `engine.cancel()`, then the previous handler (which raises `KeyboardInterrupt`).
- SIGTERM is taken over only if it is `SIG_DFL`. The first SIGTERM calls `cancel()` and raises `RunTerminated` (a `SystemExit(143)`, `:838–843`). Repeated SIGTERMs are ignored.
- Returns a function that restores the previous handlers.

**`run(question, out_dir, args, meta, plog, write_meta, *, bridge=None, gateway_factory=None, tools_factory=None)` — `:6326–6379`**
- Wraps `plog` in a `_Reporter`. If no bridge is given, imports `deerflow_research` by bare name.
- Builds the `_Engine` with `os.environ` as `env`, installs the signal handlers and returns `engine.execute()`.
- `_EngineFailure` → `status=failed`, `error`, returns **2**. [verifier: an `_EngineFailure` raised by a phase is already caught inside `execute()` (`:4197–4200`); `run`'s own handler (`:6349–6352`) only sees failures raised before `execute`, i.e. from `_Engine.__init__` such as "empty research question" (`:3950–3951`)]
- Any other `Exception` → `error="v3 engine error: …"`, `traceback`, returns **2**.
- `BaseException` → `engine.cancel()`, `error="terminated"` (for `RunTerminated`) or `"v3 engine interrupted: <Type>"`, then **re-raise**.
- `finally`:
  - `attach_telemetry()`; errors are only warnings. [verifier: only when the engine was constructed (`if engine is not None`, `:6366`); an `__init__` failure (empty question, bad work dir, factory error) gets no telemetry]
  - Forces a terminal status if none is set.
  - `write_meta()`; errors are only warnings.
  - Restores the signal handlers.
- `run` never closes `plog`. The bridge closes it (`deerflow_bridge/deerflow_research.py:16516–16560`).

---

## Control flow

```
deerflow_research._dispatch_v3_engine            (deerflow_bridge/deerflow_research.py:16516)
 └─ linear_research.run                          (:6326)
     ├─ _Engine.__init__  → _open_work_dir, factories, wrappers, run Deadline   (:3946)
     ├─ _stop_on_signals                          (:6286)
     └─ _Engine.execute                           (:4186)
         ├─ announce                              (:4166)
         ├─ phase_plan → _plan_calls(scope→_scout→plan) → build_plan/render_brief   (:4203,:4311)
         ├─ replan_after_outage (only after an outage in THIS attempt)            (:4256)
         ├─ load_followups (resume)                                              (:4363)
         ├─ phase_gather → gather_kiqs → [_run_seeds, prime, fan_out(_gather_job)]  (:4396,:4485)
         │      _gather_job → KiqAgent.run → _loop/_ask/_execute/_force_final → _finish_kiq
         ├─ phase_gap → _gap_round × n → _gap_review → gather_kiqs(follow-ups)     (:4637,:4681)
         ├─ phase_synthesize → synth_context → fan_out(_write_group→_write_single)
         │      → fallback_section_bodies → _dedup → _refill_emptied → _exec_summary (:4808)
         ├─ phase_qa → _run_qa → remove_error_markers → _repairs → _critique (deep) → _dedup
         │      → fix_scenario_weights → strip_extra_scenario_probabilities → render
         │      → renumber_citations → References → _qa_checks                      (:5166,:5194)
         └─ phase_finalize → _require_model_output → sources.json → research_report.md
                → _structured(extraction_call×2) → _write_structured → _analytics
                → bridge markets / charts / word count → return 0                    (:5526)
     finally: attach_telemetry → terminal meta.status → write_meta → restore signals  (:6365–6379)
```

Fan-out points all use `gateway.fan_out(warm_first=False, workers=preset.workers)`, which returns exceptions as results (`deerflow_bridge/research_gateway.py:1967–2000`):
- scout searches (`:4353`)
- seed searches (`:4602`)
- KIQ agents (`:4499`)
- section groups (`:4828`)
- QA rewrites (`:5327`)
- extractions (`:5638`)

Inside an agent step, tool calls run on a private `ThreadPoolExecutor` (`:3692`).

Each parallel LLM fan-out of at least 2 jobs is preceded by a single cache-priming call. The labels are `gather:prime`, `synth:prime`, `qa:prime` and `extract:prime`. `gateway.prime` never raises and is not counted by `_CallTally`.

---

## Data & artifacts

**Work dir `out_dir/v3/`** (internal, atomic writes through `rg._atomic_write_text`):

| path | written by | content |
|---|---|---|
| `state.json` | `_RunState` (`:888`) via `state.set_phase`/`mark_kiq`/`reset_*` | identity, `phases{name:{status,detail,started_at,finished_at}}`, `kiqs{id:{status,facts,verified,fallback,finished_at}}` |
| `plan.json`, `brief.md` | `phase_plan` `:4225–4226`, `replan_after_outage` `:4287–4288` | `Plan.to_dict()` (`:1105`) / the RUN BRIEF text |
| `sources_ledger.json` | `rg.SourceLedger.flush` (`:4227`, `:4431`, `:4575`, `:4668`) | sid-numbered ledger rows (`url, title, domain, tier "S1".."S3", snippet, fetched, page_path, content_sha256…`) |
| `pages/` | `rg.ResearchTools` | stored fetched page text |
| `kiq/<KID>.md`, `kiq/<KID>.json` | `_finish_kiq` `:4576–4577` | cleaned notes / the record (fields above) |
| `gap/round<n>.json` | `_gap_round` `:4707` | `{round, verdict, follow_ups:[Kiq dict], rejected:[{question,reason}], created_at}` |
| `digest.md` | `synth_context` `:4801` | the raw evidence digest with its SOURCE INDEX |
| `sections/NN.md`, `sections/NN.trimmed` | `_persist_section` `:4956` | section bodies (`00` = executive summary) and trim markers |
| `synth.json`, `synth_report.md` | `phase_synthesize` `:4866–4868` | `{exec_summary, exec_origin, exec_trimmed, sections:[{index,title,is_scenario,body,origin,trimmed?}]}` and the rendered pre-QA report |
| `qa.json`, `qa_report.md` | `phase_qa` `:5179–5180` | the QA record (fields at `:5266–5269`) and the final report including References |
| `extract/actors.json`, `extract/facts.json` | `_structured` `:5647` | `{report_sha256, result, truncated}` |
| `usage.json` | `attach_telemetry` `:5886` | the gateway usage ledger |

Section `origin` values: `writer`, `fallback`, `dropped` (synth time, `:4846`, `:5103`); `repair` and `critique` (QA time, `:5302`, `:5423`).

**Contract artifacts in `out_dir/`** (through `write_text`, i.e. the bridge's atomic writer):

| file | anchor | shape |
|---|---|---|
| `sources.json` | `:5541` | list of rows from `_source_rows` (`:5589–5601`). `[S#]` in the report is a 1-based position into this list. |
| `research_report.md` | `:5542` | `qa_report.md`. **May later get an appended prediction-markets section from the bridge** (`deerflow_bridge/deerflow_research.py:15715`). |
| `actors.json` | `:5770` | an object: `central_question, as_of_date, situation_brief, actors, relationships, hot_topics, key_events, quantitative_facts, contested_claims, forecast_inputs`, plus whatever `enforce_actor_cast` adds |
| `timeline.json` | `:5770` | `[{date, event, staleness_days?, is_stale?}]` |
| `quantitative.json` | `:5770` | normalised quant rows plus bridge enrichment and recency annotations |
| `contested.json` | `:5770` | `[{claim, positions:[{stance, sources, tier}], status, why_they_differ}]` |
| `prediction_markets.json`, charts | bridge helpers (`:5548–5551`) | not written by this slice directly |
| `meta.json` | `write_meta` callback (bridge) | this slice mutates the `meta` dict (keys listed below) |

**`meta` keys this slice sets:**
- Lifecycle: `research_engine, engine_version, depth, language, v3_workdir, status, v3_preset` (`:4167–4175`); `error, traceback, finished_at` (`:4198`, `:6350–6373`).
- Plan and synthesis: `plan_fallback`; `digest_dropped_lines`; `cross_section_duplicates_removed`; `synthesis_dropped_sections`; `synthesis_fallback_sections`; `executive_summary_origin`; `truncated_sections`.
- QA: `research_qa`.
- Extraction: `actors_skipped, actors_degraded, structured_facts_degraded, actors_truncated, facts_truncated, quant_freshness, timeline_freshness`.
- Finalize: `actors_count, relationships_count, timeline_count, quantitative_count, contested_count, has_situation_brief, report_chars, sources_count, fetched_sources_count, as_of_date, report_words, source_tiers, research_quality`.
- Telemetry: `usage, tools, phases, kiqs, analytics_errors`.

**In-memory structures:**
- `_Engine.records` (KID → record). Written under `_lock` from agent threads (`:4580–4581`).
- `_Engine.synth` and `_Engine.qa` dicts.
- `_Engine.calls` (`_CallTally`).
- `_Engine._page_numbers` cache.
- `KiqAgent._reads` (sid → focus-term sets).
- Agent `messages` list (append-only).

---

## Config / env knobs

| name | default | effect | anchor |
|---|---|---|---|
| `RESEARCH_LINEAR_<KNOB>` (17 knobs: `MAX_KIQS, AGENT_MAX_STEPS, SEARCHES_PER_KIQ, FETCHES_PER_KIQ, MAX_SEARCHES_TOTAL, MAX_FETCHES_TOTAL, GAP_ROUNDS, FOLLOWUPS_PER_ROUND, SECTIONS_MIN, SECTIONS_MAX, TARGET_UNITS, CRITIQUE, BUDGET_UNITS, TIME_BUDGET_S, WORKERS, DIGEST_CAP, MAX_TOKENS_EXTRACT`) | the depth preset (`:615–631`) | parsed by `resolve_preset` (part 1, `:698`) at `:3960`. Used throughout this slice: steps `:3511`, workers `:3691`/`:4487`, gap `:4647`, critique `:5209`, digest `:4797`, extract cap `:4005`, sections target `:4920`, budget/time `:6272`/`:4003` | `:3960` |
| `RESEARCH_MODEL_CONCURRENCY_GLOBAL` | unset | caps `preset.workers` (part 1) | `:748–754` (in `resolve_preset`) |
| `DEERFLOW_RESEARCH_TIMEOUT` | unset | `time_budget_s ≤ 0.85 ×` this (part 1) | `:755–761` (in `resolve_preset`) |
| `RESEARCH_LINEAR_MODE` | unset | `salvage` only logs that it is ignored | `:4178–4181` |
| `ACTOR_CAST_MAX` | 20 (`DEFAULT_ACTOR_CAST`, `:168`) | cast cap; 0 disables it (the prompts then say 60) | `:3962–3963`, `:4132–4134`, `:5741` |
| `RESEARCH_STALE_DAYS` | 365 (`DEFAULT_STALE_DAYS`, `:173`) | staleness threshold passed to `annotate_recency_rows` | `:5749` |
| `RESEARCH_MODEL_LEASE_WAIT_SECONDS` | research_budget default (10,800 s per `:6136`) → **capped and rewritten to 300**, then per call to the deadline-bounded wait | lease wait | `:6141–6161`, `:6219–6220` |
| `DEERFLOW_FALLBACK_MODEL` | empty (disabled) | gateway `fallback_model`. Read from `os.environ`, not from the injected `env`. | `:6264–6270` |
| `PREDICTION_MARKETS_ENABLED` | true | read by the bridge helper the slice calls | `deerflow_bridge/deerflow_research.py:15483` [verifier: the `_env_flag("PREDICTION_MARKETS_ENABLED", True)` check is at `deerflow_bridge/deerflow_research.py:15484`] |
| CLI `--depth`, `--model`, `--target-language`, `--config`, `--no-actors` | — | preset, model, language, DeerFlow config file, actor-extraction skip | `:3959–3961`, `:6245`, `:5621`, `:5714` |

Hard-coded constants that matter here (part 1 `:100–218`, plus `:3841` and `:6141–6143`):
- Size and limit gates: `MIN_REPORT_CHARS 400`, `RESERVE_SHARE 0.35`, `AGENT_CONTEXT_TOKEN_CAP 60_000`, `NOVELTY_PATIENCE 2`, `MAX_TOOL_CALLS_PER_STEP 3`, `MAX_STORED_READS_PER_AGENT 6`, `READ_DUPLICATE_JACCARD 0.65`.
- Final-notes grace: `FINAL_NOTES_GRACE_S 90`, `FINAL_NOTES_GRACE_SHARE 0.25`.
- Section sizes: `SECTION_MIN_CHARS 200`, `WRITER_BODY_MIN_CHARS 80`, `LEAD_CHARS 700`, `EXCERPT_CHARS 1200`.
- QA limits: `MAX_REPAIRS 3`, `MAX_CRITIQUE_ISSUES 5`, `MAX_CRITIQUE_REWRITES 3`, `CITATION_KEEP_RATIO 0.8`.
- Gap: `GAP_MIN_NEW_VERIFIED 3`, `GAP_DUPLICATE_JACCARD 0.6`.
- Wider-retry ceilings: `WRITER_RETRY_MAX_TOKENS 32k`, `EXTRACT_RETRY_MAX_TOKENS 64k`, `AGENT_RETRY_MAX_TOKENS 12k`, `TRUNCATION_RETRY_MIN_SECONDS 120`.
- Plan and phases: `REPLAN_MIN_REMAINING_SHARE 0.75`, `PHASE_TIME_SHARE`.
- Extraction row caps: `MAX_TIMELINE_ROWS 40`, `MAX_QUANT_ROWS 60`, `MAX_CONTESTED_ROWS 15`.
- Fallback sections: `FALLBACK_FACTS_PER_SECTION 8`.

---

## External calls

**LLM, through `rg.ModelGateway`** (retries, fallback model, usage lines, budget). Every `invoke` is counted by `_CallTally`. Labels:

| label | kind | anchor |
|---|---|---|
| `plan:scope`, `plan:plan` (and `:replan`) | json | `:4321–4341` |
| `gather:prime` | agent (prime) | `:4492` |
| `<KID>:s<n>`, `<KID>:s<n>:wide`, `<KID>:final`, `<KID>:final2` | agent + `AGENT_TOOLS` | `:3518`, `:3578`, `:3631`, `:3639` |
| `gap:r<n>` | json | `:4739` |
| `synth:prime`, `synth:g<n>`, `synth:s<i>[:wide]`, `synth:exec[:wide]` | write | `:4824`, `:5025`, `:5071`, `:5145` |
| `qa:prime`, `qa:repair:<i>[:wide]`, `qa:critique`, `qa:critique:<i>[:wide]` | write / json | `:5325`, `:5296`, `:5395`, `:5418` |
| `extract:prime`, `extract:actors`, `extract:facts` (`:wide`, `:retry1`) | json | `:5633–5704` |

**Web tools:** `tools.search` with agent ids `planner` (`:4352`), `seeder` (`:4601`) and `<KID>` (`:3790`). `tools.fetch` with agent id `<KID>` (`:3800`). They are implemented by `rg.ResearchTools` (`deerflow_bridge/research_gateway.py:3446`), which wraps the project's search and cached-fetch backends.

**DeerFlow:** `deerflow.models.create_chat_model` (`:6257`), and `deerflow.config.app_config.AppConfig.from_file` / `set_app_config` (`:6248–6251`).

**Bridge helpers** (all through `bridge_call` except `stable_source_id`, `_atomic_write_text` and `_model_call_lease`):
- `dedup_cross_section_paragraphs` `:5122`
- `enforce_actor_cast` `:5740`
- `enrich_quantitative_rows` `:5745`
- `annotate_recency_rows` `:5750–5751`
- `source_tier_histogram` `:5784`
- `compute_research_quality` `:5789`
- `_collect_prediction_markets` `:5548` (network: Polymarket, plus a possible LLM via `model_name`)
- `_render_research_charts` `:5550` (spawns a `render.py` subprocess per `deerflow_bridge/deerflow_research.py:15931–15940`)
- `count_prose_words` `:5553`
- `stable_source_id` `:5571`
- `_atomic_write_text` `:4061`
- `_model_call_lease` `:6195`

**OS-level:**
- `os.environ` mutation for the lease wait (`:6159`, `:6220`).
- Signal handlers (`:6314–6317`).
- `shutil.rmtree` of work subdirs (`:4155`, `:4249`).
- No direct subprocess and no direct DB access in this slice.

---

## Cross-module edges

**Callers into this slice:**
- `deerflow_bridge/deerflow_research.py:16526–16531`: `_dispatch_v3_engine` calls `linear_research.run(…, bridge=_bridge_module())`. Selection happens at `deerflow_bridge/deerflow_research.py:16678–16688`.
- `backend/app/services/pipeline_orchestrator.py:1357–1362` and `:1530–1536` list `linear_research.py` in `_DEPLOYED_BRIDGE_MODULES` and copy it next to the deployed `deer-flow/` script. The orchestrator never imports it.
- `backend/app/services/pipeline_orchestrator.py:5888–5900`: the engine alias table (`v3`/`linear` → v3).
- `backend/app/services/research_progress.py:31–61`, `:109–145` parse the slice's log lines into progress bands:
  - `[stage] research:v3:<phase> start (N KIQs|groups)`
  - `[ok] research:v3:gather <KID> …`
  - `[ok] research:v3:synthesize G<n> …`
  - `[ok] research:v3:qa passed=…`
  - `[done] research complete`
- `backend/app/services/pipeline_orchestrator.py:10564–10640` reads `meta.research_quality` (score and `degradation`), extends it with budget events and warns when the score is below the floor.
- Tests: `backend/tests/test_research_engine_v3*.py` (including `_text`, `_round2`, `_round3_*`, `_hardening`, `_residuals`) and `backend/tests/test_bridge_overhaul_v3.py`. They inject `gateway_factory` and `tools_factory`.

**Calls out of this slice:**
- To part 1 of this file: `resolve_preset`, `detect_language`, `actor_cast_max`, `_open_work_dir`/`_RunState`, `Plan`/`Kiq`/`OutlineSection`, `build_plan`, `render_pre_brief`, `render_brief`, `postprocess_notes`, `has_notes_heading`, `has_notes_structure`, `numeric_sentences`, `page_number_set`, `build_digest`, `split_writer_output`, `_match_title`, `_names_title`, `_section_title_key`, the scenario-frame functions (`render_scenario_block`, `parse_report_scenarios`, `scenarios_match_frame`, `fix_scenario_weights`, `scenario_weight_conflicts`, `strip_extra_scenario_probabilities`, `neutralize_scenario_markup`), the citation functions (`normalize_citations`, `strip_stale_citations`, `stale_citation_tokens`), and the templates and text tables.
- To `deerflow_bridge/research_gateway.py`: `ModelGateway`, `Deadline`, `SourceLedger`, `ResearchTools`, `ToolLimits`, `build_messages`, `estimate_tokens`, `parse_json_object`, `delimit_untrusted`, `neutralize_*`, `query_terms`, `canonical_url`, `tier_label`, the error classes, `_TRUNCATION_FINISH_REASONS`, and `_json_retry_note`/`_describe_json_failure`.
- To `deerflow_bridge/deerflow_research.py`: the bridge helpers listed under External calls.
- To `deerflow/`: the model factory and the config loader.

---

## Invariants, gates, validation

1. **Persist before marking done.**
   - KIQ notes: flush the ledger → `.md` → `.json` → `mark_kiq` (`:4575–4579`).
   - Plan: `plan.json` and `brief.md` → plan done (`:4225–4228`).
   - Synthesis: section files are written as each group finishes (`:5041`, `:5054`), and `synth.json` before synthesize done (`:4866–4871`).
   - QA: `qa.json` and `qa_report.md` before qa done (`:5179–5181`).
2. **Resume never adopts foreign artifacts.** The identity check is in `_open_work_dir` (`:973`). Artifacts are reused only after validation:
   - `Plan.from_dict` (`:1117`)
   - the KIQ record id/facts check (`:4393`)
   - the `_load_synth` title check (`:4892`)
   - the `phase_qa` shape check (`:5170`)
   - the extract memo keyed by report hash (`:5616`)
3. **Upstream changes invalidate downstream work.**
   - Any completed gather or gap KIQ invalidates synthesize, qa and finalize (`:4427–4428`, `:4724–4725`).
   - A new synthesis invalidates qa and finalize (`:4869`).
4. **Agents cite only sources they were shown.** See `_finish_kiq` (`:4558–4563`) and `_cites_shown_source` (`:3501–3508`).
5. **The report cites only citable sources.** Citable means the digest's SOURCE INDEX plus fact sids (`:5272–5282`). Other markers are dropped by renumbering (`:5258–5259`).
6. **References and `sources.json` equal the cited set, in positional order.** See `:5258–5260` and `:5535–5536`.
7. **`sources.json` is written before `research_report.md`** (`:5538–5542`), so a report is never on disk without its sources.
8. **A bare heading is never published.**
   - `render_report` skips empty non-scenario sections (`:3207–3208`).
   - `_refill_emptied` rebuilds or drops sections (`:5087–5112`).
   - `trim_cut_reply` drops heading-only tails (`:3144–3145`).
9. **No UNVERIFIED finding appears in a deterministic section** (`:3878`).
10. **Budget reserve.** Agent steps, agent wider retries and gap rounds use `keep_reserve=True` and may not touch the last 35% of the budget (`:3624`, `:3601`, `:4691`). Writer, extract and QA work uses `keep_reserve=False` (`:4982`, `:5321`, `:5362`).
11. **Output gates.**
    - Exit 0 requires a final report of at least 400 stripped characters (`:5531`) and some model output, unless the cause was a content filter or the budget (`:5498–5524`).
    - QA checks are advisory (`:5264–5266`).
12. **`meta.status` is always terminal** when `run` returns or raises (`:6371–6373`).

---

## Failure modes & recovery

| failure | handling | resumability | anchor |
|---|---|---|---|
| empty question | `_EngineFailure` from `__init__` → rc 2 | — | `:3950`, `:6349` |
| scope/plan call fails | scope → single fallback scout query; plan → deterministic `build_plan` defaults; an outage sets `model_unavailable` | an outage plan with no evidence is re-planned on resume (`_discard_outage_plan`); one bounded re-plan in the same attempt | `:4326–4344`, `:4234`, `:4256` |
| agent provider error | `abort` stops new KIQs; deterministic `provider` notes are kept if the agent fetched pages; the error propagates | `provider` is retryable on resume | `:4534–4544` |
| agent non-provider error, deadline, budget, unusable notes | deterministic notes; the category is recorded as `fallback` | `deadline, budget, unstructured_notes, no_sourced_facts, notes_truncated` are retried on resume; `content_filter`, `empty`, `error_*` and `no_final_text` are not | `:3480–3490`, `:214` |
| gather: no sourced fact | KIQs reset, gather `failed`, `evidence_unavailable` → rc 2 | full re-research on resume | `:4471–4483` |
| gather: provider error, fewer than half the plan KIQs agent-written | gather `failed`, `provider_unavailable` → rc 2 | yes | `:4442–4447` |
| gather: provider error, at least half written | gather `partial`, continue, degradation event | the missing KIQs are researched on resume (pending check `:4415`) | `:4448–4456` |
| gap provider error / exception | gap `partial` or a `stopped:` detail; continue | the persisted round is reused and pending follow-ups researched, unless synthesize is done [verifier: only for `partial` (provider failures). A non-provider exception (e.g. `JsonUnparseable` from the `gap:r<n>` review) or a non-provider stop reason leaves gap `done` with a `stopped…` detail (`:4651–4664`, `:4669`), so a resume skips the phase entirely (`:4642–4646`)] | `:4652–4669`, `:4643` |
| group writer failure / missing section | single-section retry → deterministic bullets [verifier: no single-section retry when the group call failed with `BudgetExhausted` or `DeadlineExceeded` (`retry=False`, `:5045–5050`); the bullets are built later in `phase_synthesize` (`:4842–4847`) and are `- <no_evidence>` when no sourced, non-UNVERIFIED finding is available (`:3912–3915`)] | the written sections are persisted and reused | `:5043–5058` |
| truncated writer reply | wider retry (single section/exec), else `trim_cut_reply`; flagged `trimmed` (QA `complete_sections` fails) | the marker file survives resume | `:4984–5014`, `:4956–4968` |
| synthesis provider error | synthesize `failed`, `provider_unavailable` → rc 2 | the written sections are reused | `:4859–4862` |
| QA rewrite failure or budget | the rewrite is skipped (`None`); the section is kept | — | `:5306–5343`, `:5362–5370` |
| critique provider error | caught and logged; QA continues | — | `:5213–5214` |
| no model output at all | KIQs and records reset, gather–qa invalidated, `provider_unavailable: no model output` → rc 2 | yes | `:5498–5524` |
| report < 400 characters | finalize `failed`, `report_too_short` → rc 2 | yes | `:5531–5533` |
| extraction failure | deterministic fallback (planner actors / empty facts) and degradation events | the memo prevents paying twice | `:5639–5643`, `:5719–5725` |
| bridge helper missing or raising | recorded in `meta.analytics_errors`, returns `None` | — | `:4080–4091` |
| lease capacity timeout | leasing is disabled for the rest of the run (one warning) | — | `:6206–6231` |
| SIGTERM | `cancel()` (no new paid calls, tools return CANCELLED), `RunTerminated` unwinds, `meta.error="terminated"`, re-raised (exit 143) | yes (phases persisted) | `:6306–6312`, `:6358–6364` |
| unexpected exception | rc 2 with `meta.traceback`; the phase stays `running` in `state.json` | the phase reruns on resume | `:6353–6357` |

---

## Surprises

1. **The slice holds the whole engine, not only synthesis.** `_Engine` (`:3943–5904`), including the plan, gather and gap drivers, and `KiqAgent` (`:3422`) live in "part 2". Part 1 is only building blocks. [verifier: structure confirmed; but part 1 is not only pure helpers — `_RunState` (`:888`), `_CallTally` (`:846`) and `_open_work_dir` (`:973`, renames stale work dirs) are stateful/IO]
2. **No judge.** v3 has no AI judge. `compute_research_quality(…, judge_scorecard=None, …)` (`:5789–5790`). Validation is the deterministic `_qa_checks` plus the deep-only critique. `README.md:695` agrees: "no … judge scorecard".
3. **QA `passed=false` never blocks publication.** Only report length and model output gate exit 0 (`:5264–5266`, `:5531`, `:5498`). [verifier: overstated — within finalize yes, but earlier gates also return 2: `evidence_unavailable` / `provider_unavailable` in gather (`:4434–4447`, `:4482–4483`), synthesis `provider_unavailable` (`:4859–4862`), and any unexpected exception, including one raised in finalize after `research_report.md` is already on disk (`:5545–5562`, `:6353–6357`)]
4. **Two `_wider_cap` methods with different signatures and reserve rules.** `KiqAgent._wider_cap(messages, cap)` uses `keep_reserve=True` (`:3588–3601`). `_Engine._wider_cap(kind, messages, deadline, *, ceiling, cap)` uses `keep_reserve=False` (`:4970–4982`). The formula is duplicated.
5. **Inconsistent wider-retry error policy.**
   - `_write_call` and `KiqAgent._ask` re-raise provider errors from the wider retry (`:5003–5004`, `:3580–3581`).
   - `extraction_call` catches every `rg.GatewayError` there, including `ProviderUnavailable`/`QuotaExhausted`, and keeps the cut reply (`:5693–5698`).
   - The group writer call `synth:g<n>` has **no** wider retry at all; it relies on `_write_single` for the cut section (`:5023–5031`).
6. **Suspected: wrong section popped.** `_write_group` pops the last assigned title present in `parsed` *in outline order* (`:5029–5031`). If a writer emits sections out of order, the popped section may not be the one the cap actually cut, and the truly cut section is persisted untrimmed.
7. **Dead in production.** `_Engine._fallback_section` (`:5082–5085`) is only used by `backend/tests/test_research_engine_v3_text.py:148`.
8. **The report on disk can differ from the QA report.** `_collect_prediction_markets` may rewrite `research_report.md` after the engine wrote it (`deerflow_bridge/deerflow_research.py:15715`). So `v3/qa_report.md` and `qa.json.report_sha256` describe the pre-markets text. Finalize re-reads the file only for `report_chars` and the word count (`:5552`).
9. **Finalize always reruns.** It has no `is_done` skip (`:5526–5568`), so a resume of a completed run rewrites every contract file and calls the prediction-market and chart helpers again (network, possibly LLM). Only extraction is memoised (`:5614–5620`).
10. **Suspected: degradation events can be lost.** They are surfaced only if `compute_research_quality` returns a dict (`:5791–5799`). If the helper is missing or raises, they are not recorded anywhere in meta (only `analytics_errors`). [verifier: the folded event list (and its warn log) is indeed lost (`:5791–5799`), but most underlying signals survive as separate meta keys: `truncated_sections`, `synthesis_fallback_sections`, `executive_summary_origin`, `plan_fallback`, `actors_degraded`, `structured_facts_degraded`, `<kind>_truncated`, `kiqs.fallback` and `phases.gap` (`:4873–4875`, `:4230`, `:5722–5724`, `:5650`, `:5892–5902`); a non-dict return that does not raise leaves no `analytics_errors` entry either (`:4080–4091`)]
11. **Suspected: some fallback sections go unreported.** `_degradation_events` lists fallback sections from the **synth-time** origins (`:5861–5862`). A writer section that was emptied by QA dedup and refilled with deterministic bullets in `_run_qa` (`:5220`) is not reported as a fallback section.
12. **Error-marker removal runs before QA rewrites** (`:5200–5207`). An error line inside a rewrite would fail `no_error_markers` (`:5441`, `:5467`) instead of being removed. This is low-likelihood, because the gateway raises on provider errors.
13. **`JsonUnparseable` hides its detail.** `str(exc)` is always `"json_unparseable"`, and the detail lives in `.detail` (`deerflow_bridge/research_gateway.py:200–211`). Engine warnings formatted as `({exc.category}: {exc})` (e.g. `:4344`, `:5399`, `:5641`) therefore print `json_unparseable: json_unparseable` and lose the diagnostic. [verifier: `:5641` uses a different format, `({type(result).__name__}: {result})`, printing `JsonUnparseable: json_unparseable`; it also loses the detail]
14. **Abbreviation gotcha.** `_ABBREVIATION_RE`'s single-initial rule `(?<![\w.])[A-Z]\.` (`:3081`) means a sentence ending in a lone capital ("…called Plan B.") is not a sentence end, so `trim_cut_reply` or `sentence_excerpt` may cut earlier than expected. "No." is also listed as an abbreviation.
15. **Inconsistent source labels.** `sources.json` calls snippet-only sources `"cited"` (`:5592`), References call them `"search snippet"` (`:3296`), and the `date`, `supports` and `independent` fields are always placeholders (`None`, `[]`, `None`; `:5591`, `:5600–5601`).
16. **`normalize_actor_rows(…, cap)` is always called with cap 0** (`:5719`). The real cast cap is applied by the bridge (`enforce_actor_cast`), or by a model-order slice when the bridge's cut did not run (`:5740–5744`).
17. **`os.environ` is mutated.** `_cap_lease_wait` and `lease()` write `RESEARCH_MODEL_LEASE_WAIT_SECONDS` process-wide (`:6159`, `:6220`). The module docstring calls this the one exception to "never mutates os.environ" (`:46–49`). `DEERFLOW_FALLBACK_MODEL` is read from `os.environ`, not from the injected `env` (`:6264`).
18. **Suspected, low impact: the re-plan can hit the planner's search budget.** Re-plan scout searches that miss the search cache count against the `planner` allowance of 6 searches already used by the first scout [verifier: plausible but conditional — the first scout may have used fewer than 6 (a failed scope leaves one fallback query, `:4329–4330`); exhaustion needs the re-plan to issue new uncached queries beyond what is left, or retries of failed first-scout searches, which are never cached (`deerflow_bridge/research_gateway.py:3572–3583`)] (`:3985`, `deerflow_bridge/research_gateway.py:3568–3571`). A re-plan whose scope now yields different queries can get `SEARCH_BUDGET_EXHAUSTED` rows in its digest.
19. **`no_final_text` is not retried on resume.** An empty, untruncated final reply leaves `final_issue=None`, so the fallback is `no_final_text` (`:3475`, `:3642–3650`), which is not in `_RETRYABLE_FALLBACKS` (`:214–215`). A resume will not research that KIQ again. [verifier: trigger is imprecise — an empty reply (no text, no tool calls) raises `EmptyResponse` in the gateway (`deerflow_bridge/research_gateway.py:1782–1784`) and ends as fallback `empty` (`:3484–3485`); `no_final_text` comes from a final reply with tool calls but no text (`:3634–3640`). Neither is retryable, so the conclusion stands]
20. **Doc vs code drift:**
    - `README.md:477` and `README.md:491` say "Nine deterministic checks". The code adds a tenth, `language`, for Chinese reports (`:5472–5474`).
    - `deerflow_bridge/README.md` never mentions v3 or `linear_research`; it describes research driven through `DeerFlowClient`. v3 only uses DeerFlow's model factory and config.
    - Code comments cite `V3_SPEC §…` (`:3231`, `:3335`; module docstring `:3`), but no `V3_SPEC*` file exists in the checkout.
    - `.env.example:305` describes `DEERFLOW_FALLBACK_MODEL` for the legacy "outline/section/judge" calls. In v3 it is the gateway's general `fallback_model` (`:6271`).
    - `RESEARCH_STALE_DAYS` and `RESEARCH_MODEL_LEASE_WAIT_SECONDS` are not documented in `.env.example`.
    - The `_qa_checks` detail string hardcodes "200 characters" instead of using `SECTION_MIN_CHARS` (`:5451`).

---

## Verification

Adversarial check of this map against `deerflow_bridge/linear_research.py` on `main` (read-only; no code was run). Anchor convention as above. Inline `[verifier: …]` notes mark each corrected statement.

**Verdict counts.** 15 key claims: 10 confirmed, 5 imprecise, 0 refuted. 18 surprises: 14 confirmed, 4 imprecise, 0 refuted. Map-only spot checks: about 60 Walkthrough / Control-flow / table statements re-read against code; 9 found imprecise (listed below), the rest confirmed.

**Key claims that are not confirmed (with corrections):**
1. *run() boundary* — imprecise. `_EngineFailure` from a phase is caught inside `execute()` (`:4197–4200`); `run`'s own `_EngineFailure` handler (`:6349–6352`) only sees `_Engine.__init__` failures. The `finally` attaches telemetry only `if engine is not None` (`:6366`), so it is not "always".
2. *Only exit-0 path* — imprecise. True that only `phase_finalize` returns 0 (`:5568`), but `_require_model_output` does not strictly require model output: it lets the run publish when the content filter refused calls or when no call `failed` (`:5509–5518`). Also, an unexpected exception after `research_report.md` is written still yields rc 2 (`:5545–5562`, `:6353–6357`).
3. *Per-step tool limits* — imprecise. The 3 slots are counted by position before screening, so refused or duplicate calls use a slot (`:3670–3673`). A same-step twin read of a stored page gets `ALREADY_READ_TEXT`, not `DUPLICATE_CALL_TEXT` (`:3676–3682`, `:3766–3771`). The 6-read allowance covers every read of an already-stored page, including the first read of a page another agent fetched, not only re-reads (`:3756–3772`, comment `:114–117`).
4. *Wider retry* — imprecise. Not every cut reply: the group writer call `synth:g<n>` has none (`:5023–5031`); agent replies with tool calls and provider-aborted replies are not widened (`:3569–3571`, `:4994–4996`, `:5682`). "Exactly one" is "at most one". Truncated group replies are not trimmed but lose their last found section (`:5028–5031`).
5. *Synthesis groups* — imprecise. Formula confirmed (`:4910`), but singles are skipped (`retry=False`) after a group `BudgetExhausted`/`DeadlineExceeded` (`:5045–5047`); the deterministic bullets are built in `phase_synthesize` (`:4842–4847`), not by `_write_group`, and are `- <no_evidence>` when no eligible finding exists (`:3914–3915`).

**Surprises that are not confirmed (with corrections):**
- *Part 1 is only pure building blocks* — imprecise: `_RunState` (`:888`), `_CallTally` (`:846`) and `_open_work_dir` (`:973–994`) are stateful/IO. The structural point (whole `_Engine` + `KiqAgent` in part 2) is confirmed (`:3422`, `:3943`).
- *Degradation events lost* — imprecise: the folded event list is lost when `compute_research_quality` is missing, raises or returns a non-dict (`:5789–5799`); a non-dict return records nothing in `analytics_errors` either (`:4080–4091`). Most underlying signals still reach meta as separate keys (`:4873–4875`, `:4230`, `:5650`, `:5722–5724`, `:5892–5902`).
- *`no_final_text` trigger* — imprecise: an empty untruncated reply raises `EmptyResponse` in the gateway (`deerflow_bridge/research_gateway.py:1782–1784`) and ends as `empty` (`:3484–3485`); `no_final_text` comes from a final reply with tool calls but no text (`:3634–3640`). Both are non-retryable (`:214–215`), so the conclusion holds.
- *Re-plan planner budget* — imprecise (overstated "already used"): the first scout may use fewer than 6 searches (a failed scope leaves one fallback query, `:4329–4330`). Exhaustion needs new uncached queries beyond what is left, or retries of failed searches, which are never cached (`deerflow_bridge/research_gateway.py:3568–3583`).

**Map-only statements found imprecise (inline notes added):**
- Purpose item 3, "a reply cut by its output cap is retried once with a wider cap, then trimmed": not for group calls (see claim 4).
- `_without_cut_item` returns `None` only when no line is a list item (`:3116–3118`).
- `_not_notes`, "an empty, untruncated final … `no_final_text`" (see `no_final_text` surprise).
- `_execute` slots, `_repeats_in_step` duplicates, and the "ThreadPoolExecutor" line: a single runnable call runs inline (`:3688–3689`).
- `run`: `_EngineFailure` handler scope and conditional telemetry (claim 1).
- Config table: `PREDICTION_MARKETS_ENABLED` is read at `deerflow_bridge/deerflow_research.py:15484`, not `:15483`.
- Failure table, group writer row: missing the `retry=False` case and the no-evidence placeholder.
- Failure table, gap row: only `partial` (provider) is resumable. A non-provider exception or stop leaves gap `done` with a `stopped…` detail (`:4651–4669`), and a resume skips the phase (`:4643–4646`).
- Surprise 3, "Only report length and model output gate exit 0": gather (`:4434–4447`, `:4482–4483`) and synthesis (`:4859–4862`) failures and unexpected exceptions also return 2.
- Surprise 13: `:5641` formats `({type(result).__name__}: {result})`, not `({exc.category}: {exc})`. It still loses the detail.

**Spot checks confirmed (sample):** `trim_cut_reply` paragraph logic (`:3125–3146`); `sentence_excerpt` cut order (`:3149–3178`); `_collapse` cuts at a space in the last 40% (`:545–554`); `render_report` omits empty non-scenario sections (`:3200–3213`); `strip_references` last `## References` only (`:3216–3227`); `renumber_citations`/`render_references` (`:3274–3299`); `citation_density` `> 200` chars (`:3320–3331`); `tool_output_sids` untrusted-block skip (`:3346–3369`); `_pressure` order (`:3618–3626`); `_final_notes_grace` formula with agent timeout 240 (`:4511–4521`, `deerflow_bridge/research_gateway.py:574`); presets 5/7/9 steps and 1200/2700/5400 s (`:615–631`); `PHASE_TIME_SHARE` is a share of remaining time (`:176–178`, `deerflow_bridge/research_gateway.py:1074–1081`); gap gate/capacity/review rules (`:4672–4767`); `fallback_section_bodies` rank tuple (`:3894–3909`); QA step order (`:5194–5270`); `_rewrite_section` adoption rule (`:5350–5383`); `_source_rows` placeholders (`:5581–5603`); `extraction_call` swallowing provider errors on the wide retry (`:5693–5698`); `_bridge_lease` turn/ended locks (`:6178–6234`); `_stop_on_signals` (`:6286–6323`); `_dispatch_v3_engine` closes `plog` (`deerflow_bridge/deerflow_research.py:16516–16561`); `fan_out` returns exceptions as results (`deerflow_bridge/research_gateway.py:1967–2000`); `gateway.prime` bypasses the watched `invoke`, so `_CallTally` does not count it (`deerflow_bridge/research_gateway.py:1921–1961`).

**Omissions (significant behavior the map does not state):**
1. **Exit code can be 2 with a published report.** After `sources.json` and `research_report.md` are written (`:5541–5542`), any non-`_EngineFailure` exception, such as an `OSError` from a contract write in `_write_structured` (`:5770`) or the extract memo write (`:5647`), reaches `run`'s generic handler and returns 2 with a traceback (`:6353–6357`). Finalize then stays `running` in `state.json`. This contradicts the docstring "returns 0 iff research_report.md (>= 400 chars) was written" (`:6329`). The parent's salvage path depends on the report on disk (comment `:5538–5540`).
2. **Log order differs from write order.** `sources.json` is written before the report (`:5541–5542`), but the log says `wrote research_report.md` first and `wrote sources.json` second (`:5543–5544`). `backend/app/services/research_progress.py:62–64` assigns its progress bands from that log order.
3. **A resumed attempt that reuses synthesis drops several meta keys.** The bridge builds `meta` fresh for every process (`deerflow_bridge/deerflow_research.py:16781–16796`; prior meta is carried over only for extract-only salvage, `:16799–16809`). The synthesize reuse path sets only `truncated_sections` (`:4809–4814`). So `synthesis_fallback_sections`, `executive_summary_origin`, `cross_section_duplicates_removed`, `synthesis_dropped_sections` and (when `digest.md` is reused) `digest_dropped_lines` are absent from that attempt's `meta.json` (`:4798`, `:4849–4854`, `:4873–4874`). The degradation events are unaffected, because they read `self.synth` (`:5859–5862`).
