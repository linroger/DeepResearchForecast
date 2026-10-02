# What DeepResearchForecast takes from FinanceHarness, StockAgent, TradingAgents and five papers

**Branch** `feat/finharness-transplants` · **Code anchors** DRF at `1e40844` (the code the study read) · **Implementation** 81 of 81 work packages merged, plus 12 follow-up packages; 19 deferred with recorded evidence · **Assembled** 2026-10-03 at `d5923c1`

This document distils what three codebases and five papers do well, keeps only what survives adversarial verification against DeepResearchForecast (DRF), and records how it was implemented on the branch above. Every new behaviour sits behind a `Config` knob documented in `.env.example`. With a knob at its default, output is byte-identical to before unless the knob's entry says the default is on.

### How to read it

1. **The essence across all eight sources**: seven principles, each linked to the work packages that implement it. Start here.
2. **Source chapters**: one per codebase and one per paper. Each gives the essence, the architecture or method, what the evidence actually shows, the mechanisms worth transplanting (ranked, with their DRF gap), and what not to transplant.
3. **Implementation roadmap**: the plan as approved (81 work packages in 15 waves, 19 deferred), with its integration rules.
4. **Implementation record**: what landed, wave by wave, with the knobs, the gate results and the integration fixes.
5. **Appendices**: the ledger of all 83 candidates with their verifier verdicts, and every work package with its outcome.

**Anchors.** `path:line` cites code. A path that starts with `FinanceHarness-0.1.0/`, `Stockagent-main/` or `TradingAgents-0.5.1/` points into the finharness sources; every other path is DRF at `1e40844`, the program's baseline (line numbers on the branch have since moved). `KEY p.N` cites a page of a paper's PDF. Every anchor was checked twice. First mechanically: the file exists at that revision and the line range lies within it, and the page lies within the paper (follow-on ranges and pages included). Then for content: read-only verifier agents compared each of the 1,381 anchored statements with the cited lines or PDF page. 1,272 held as written; 109 were corrected (wrong line ranges, facts cited to the wrong page, and some claims the evidence contradicted). The verifiers' notes led to 13 further editorial fixes.

### Sources

| Key | Source | What it is | Size | Licence and use |
|---|---|---|---|---|
| FH | FinanceHarness 0.1.0 (code) | Autonomous financial deep-research agent runtime: skills, tool registry, reference chaining, context budget, recovery, citations, finance compute tools | 94 files, ~9k lines | No licence shipped: ideas reimplemented, no code copied |
| SA | StockAgent (code) | LLM-agent stock-market simulation; a "secretary" validates every agent decision | 31 files, ~1.6k lines | No licence shipped: ideas reimplemented, no code copied |
| TA | TradingAgents 0.5.1 (code) | Multi-agent trading firm on LangGraph: analysts, bull/bear debate, trader, risk debate, portfolio manager, decision-log memory, point-in-time data | 196 files, ~24k lines | Apache-2.0 |
| FHP | FinanceHarness (paper, arXiv 2607.27853) | Point-in-time benchmark and harness for financial research reports: search capped at the question's cutoff, two-tier rubric (evidence retrieval vs anticipation) | 55 pages | Cited, not copied |
| SAP | StockAgent (paper, arXiv 2407.18957) | LLM traders in a closed simulated market; swapping the backbone model reversed the market | 33 pages | Cited, not copied |
| TIEM | TIEM (arXiv 2608.13024) | Event-driven return-sign forecasting with a point-in-time input contract, hypergraph evidence and ancestry-gated skill memory | 23 pages | Cited, not copied |
| NEX | Nexus (arXiv 2605.14389) | Agentic time-series forecasting: four LLM roles and a calibration agent whose rules must beat the latest held-out fold | 30 pages | Cited, not copied |
| F2A | F²Agent (arXiv 2608.05668) | Multimodal trading agent: separate per-channel processors, learned fusion, channel-corruption robustness | 32 pages | Cited, not copied |

### Method

1. **Reading.**
   - 14 repo readers covered 281 of the 282 source files; the last one, TradingAgents' `LICENSE`, was read directly. They recorded 228 mechanisms.
   - 12 paper readers, using method, evidence and temporal-integrity lenses, read every page of the five papers and recorded 167 mechanisms.
   - 6 DRF cartographers mapped the six pipeline stages: research, ontology, graph, prepare, simulation and report.
2. **Candidates.**
   - Clustering produced 48 repo candidates (C01–C48). A completeness critic added four more (N01–N04).
   - Merging the paper mechanisms produced 31 paper candidates (P01–P31), 19 of which extend a repo candidate.
   - Eleven paper mechanisms were rejected with reasons, among them fine-tuning, reinforcement learning, trading-return objectives, hidden-state fusion, random trader personas and endowments, trading-account mechanics, and cross-stock theme clustering that needs a dense multi-entity corpus.
3. **Verification.** Each of the 83 candidates was mapped to DRF: the file and function it attaches to, what DRF already has, and the exact delta. Three adversarial lenses then checked it:
   - *source*: does the source really do this?
   - *gap*: does DRF really lack it?
   - *value*: would it make DRF's forecasts better? This lens judged on real DRF artifacts, such as the 29-row production ledger and the stored reports.
4. **Planning.**
   - Six area planners and an integrator produced 100 work packages: 81 to implement and 19 deferred.
   - A plan critic checked every package against the code and added 79 amendments, 3 of them blocking.
   - Dependencies were verified mechanically.
5. **Implementation.**
   - Each package was built in its own git worktree by an implementer. An adversarial reviewer and a fixer then worked on it until the reviewer approved. Most packages needed one to three review rounds; the hardest (REPORT-13) needed seven. Low-severity issues left at approval were fixed before the merge or recorded under "Open issues after implementation".
   - The orchestrator merged each wave into the integration branch and gated it on the full offline backend suite plus the frontend unit tests.
   - Tests use `FakeLLMClient`: no network and no live models.

## The essence across all eight sources

Three codebases and five papers were studied: FinanceHarness (code and paper), StockAgent (code and paper), TradingAgents, TIEM, Nexus and F²Agent. They look different: a research harness, a toy market, a simulated trading desk, a timestamp-gated forecaster, an agentic time-series forecaster and a multimodal trader. Their durable lessons for DRF converge on seven principles.

What does *not* transfer is just as consistent. None of the eight sources shows, with adequate evidence, that its headline *architecture* causes its results:

- TradingAgents never ablates its role-play desk.
- The component deltas in Nexus are 1–4% from single runs.
- TIEM's hypergraph and skill memory rest on 128-case test sets.
- F²Agent's up/down accuracy is near chance on one bull-market window.
- The StockAgent paper's clearest result is that swapping the backbone model reversed the market.

What transfers is the *discipline* around the architecture: time, absence, provenance, validation and measurement.

### 1. Time is part of the input contract

A forecast is only meaningful if every input can be shown to have been available at decision time, and each source enforces this mechanically.

- **TradingAgents** injects the run date server-side, hides it from the model, clamps every tool date window to it, and withholds data that exists only live (odds, snapshots) from past-dated runs.
- **TIEM** gives every record an availability time. Focal evidence uses a non-strict gate (≤ T) and prior facts a strict one (< T). A derived aggregate becomes available only when its latest child does. A learned lesson is usable only if every case in its ancestry resolved before T; missing ancestry fails closed.
- **The FinanceHarness paper** makes this the benchmark contract: search returns only documents published on or before the cutoff, and a leak invalidates the run.
- **Nexus** scores only targets after the model's knowledge cutoff.

**DRF implication:**
- Pin the as-of date so the model cannot overwrite it (TIME-1).
- Gate expired prediction markets (TIME-3).
- Capture source publication dates (TIME-2).
- Build an honest, opt-in hindcast lane with admission control, point-in-time evidence gates and a citation wall (TIME-6 … TIME-9).
- Record the time basis of every market price (EVAL-6).

### 2. Absence is information, never a fact

The most repeated fix in TradingAgents' fifteen-month changelog is refusing to let missing or ambiguous data pass as a finding:

- an unreadable rating becomes a `REVIEW` sentinel, never Hold;
- an empty prompt slot is named as absent;
- a window a feed never observed is reported as unavailable, not empty.

FinanceHarness labels failed reads "unread" rather than dropping them silently.

**DRF implication:**
- Probability parsing gets an explicit needs-review state instead of laundering garbage into uniform splits (REPORT-1).
- Typed absence markers go into every report-stage prompt slot (REPORT-4), and the simulation world clock separates first, quiet, failed and not-stepped periods (REPORT-6, SIM-6).
- Research tools report "no results were observed", not "none exist" (RESEARCH-3).
- Source failures are counted honestly by type (RESEARCH-2).

### 3. The harness owns evidence and arithmetic; the model owns judgment

**FinanceHarness:**
- It gives a URL a citation number only after a successful fetch and a reader verdict that the page is real content.
- It rebuilds the bibliography at exit from what was actually read.
- It does exact arithmetic in an always-visible `calc` tool.
- It passes bulk data between tools by reference, so numbers are never retyped through the model.

**StockAgent's "secretary"** is really a deterministic validator. It checks every LLM decision against live state and returns the specific broken constraint for a repair turn.

**DRF implication:**
- Type and page-verify quantitative rows once (RESEARCH-4).
- Carry evidence windows and verbatim spans (REPORT-7, RESEARCH-7).
- Render a labelled verified-figures block (REPORT-8) and shadow-check published figures (REPORT-9).
- Record citation surgery instead of hiding it (RESEARCH-9).
- Add declarative DERIVED findings with a hardened evaluator (RESEARCH-8).
- Do market-blend arithmetic in code that shows its work (REPORT-12).
- Keep narrative numbers in sync with the forecast (REPORT-2, REPORT-3).

### 4. Validate every model output against live state, and repair with a reason

- StockAgent's secretary loop: validate, give a specific reason, retry up to three times, then take an explicit no-op default.
- TradingAgents' structured outputs with a review sentinel.
- FinanceHarness's schema-driven argument coercion and a dispatcher that never raises.

All three are the same pattern.

**DRF implication:**
- Roster-bound validation of simulation decisions with reason-coded accounting (SIM-1, SIM-2).
- A structured-output repair turn that discards failed attempts from the cache (INFRA-2).
- Transport normalisation for truncated or filtered replies (INFRA-1, INFRA-3).
- A tolerant but validated report tool-call boundary (INFRA-5).
- Non-finite-number guards (INFRA-4).

### 5. Close the learning loop, but only in a way that respects time

**TradingAgents' loop:**
1. Log each decision as pending.
2. Settle it only after the full outcome window has traded.
3. Reflect on it with a prompt that names the window.
4. Stamp it with the date its outcome became knowable.
5. Show it to a later run only if that run's as-of date is on or after the stamp.

**Complementary gates in the papers:**
- TIEM adds ancestry gating for lessons.
- Nexus adds a held-out, time-ordered gate: a learned correction must beat the latest fold by at least 5% before it touches live forecasts.

**DRF's ledger:**
- The verifiers read DRF's real ledger. It has 29 rows and none has resolved; most horizons fall in 2030–2036.
- At most 5 of the rows are publishable.
- Some forecasts repeat 7 times.

**DRF implication:**
- Make the track record real before learning from it: commit the exact sealed, published bytes once (EVAL-1).
- Settle markets with honest "known-at" times (EVAL-2).
- Add a single point-in-time admissibility fold (EVAL-3).
- Add a manual settlement path (EVAL-4); only 1 of 344 stored binaries has an exact market anchor, so this is the only realistic label source.
- Score skill relative to the market the forecast saw (EVAL-5).
- Keep evaluation runs out of production calibration (EVAL-13).

The qualitative lessons memory (P16) and held-out recalibration promotion (P04) are **deferred on evidence**: with no resolved labels they would sit dormant, and ADR 0002 restricts what may move a published probability.

### 6. The backbone model is a variable to measure, not a constant

- **StockAgent:** swapping GPT-3.5 for Gemini-pro under identical inputs reversed the simulated market (r = −0.86).
- **The FinanceHarness paper:** all 18 systems score only 5–13% on post-cutoff anticipation items.
- **TIEM:** a name–date probe measures what a model "knows" without the evidence.

**DRF implication:**
- A shadow cross-backbone sensitivity check that flags model-dependent forecasts without changing any published probability (EVAL-11).
- Contamination probes for golden evaluation (EVAL-12).
- A zero-LLM prior-echo diagnostic for the decision channel (SIM-4).
- An A/A noise floor before any stage-attribution claim (EVAL-19, EVAL-20).

### 7. Evaluation hygiene beats architecture

The part of each paper that transfers is its evaluation protocol:

- TIEM's contamination inspection and availability audit;
- the FinanceHarness paper's two-tier rubric;
- Nexus's post-cutoff holdout;
- StockAgent's fictional-ticker control, read against its missing controls.

DRF's golden set has 30 questions, all resolved between January 2024 and February 2025, which is inside every current backbone's training data.

**DRF implication:**
- A golden-eval honesty layer with confidence intervals and duplicate-id fixes (EVAL-7).
- Headline tiering that separates prospective from hindcast rows (EVAL-8).
- A golden-set v2 data contract with outcome-free criteria and a leak lint (EVAL-9).
- A per-stage scorecard (EVAL-15, EVAL-16).
- A cost card with per-stage metering fidelity (EVAL-17, EVAL-18).
- Structured numeric targets with a threshold-ladder audit (EVAL-14).

### What DRF deliberately does not take

**Architecture and training:**
- The trading-desk role-play: bull/bear and risk debates are never ablated. DRF gets one evidence-cited counter-case pass, default off (REPORT-13).
- Fine-tuning and reinforcement learning (F²Agent's instruction tuning, the FinanceHarness paper's GRPO, which added only +0.4, inside the noise).
- Learned hidden-state fusion (F²Agent), because DRF uses hosted APIs.

**Simulation design:**
- Random personality archetypes (StockAgent), which the owner rejected in favour of dossier-grounded real actors.
- Loans, fees and bankruptcy mechanics.
- HDBSCAN cross-entity themes (TIEM): no ablation, and about 0.23 themes retrieved per case.
- An intra-simulation belief market (deferred).

**Research stage:**
- Search pre-flight with cache warming. In the FinanceHarness paper, removing its URL pre-validation raised the visit error rate from 2.1% to 39.4% while "the end score barely moves", so it does not improve DRF's forecasts.

## FinanceHarness

### 1. Essence

FinanceHarness (FH) is a single-agent financial deep-research harness of about 8.6k lines of Python, released alongside arXiv 2607.27853. It has one bounded native tool-calling loop (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:296-426`) over a dispatcher designed never to raise (`FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:106-217`). Seven tools are always visible and fourteen are deferred, the deferred ones being yfinance data plus pure-math valuation and risk tools (`FinanceHarness-0.1.0/README.md:119-133`). On top of that sit five SKILL.md recipes and a deterministic citation finalizer that runs at the loop's single exit (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:428-460`).

Two ideas make it distinctive:

- **The model reasons, the tools do the arithmetic, and bulk data moves by reference.** Every tool returns markdown for the model and a structured payload for the machine (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:46-55`). A later call can consume that payload through a `prev:<call_id>.<path>` reference, which is resolved *before* schema validation (`FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:137-159`). An exact `calc` tool is always visible (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:114-122`).
- **The harness, not the model, owns the evidence.** A URL gets a citation number only after a successful fetch *and* a reader verdict that the page is real content (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:175-194`). A failed read is labelled "unread" to the model (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:124-131`). At exit, the bibliography is rebuilt from what was actually read and model-written references are stripped (`FinanceHarness-0.1.0/financeharness/runtime/citations.py:42-96`).

There is no LICENSE file, so ideas may be reimplemented but no code may be copied. The repo ships no tests (`find` over the tree finds none).

### 2. Architecture at a glance

```
question (+ answered clarifications)                         FinanceHarness-0.1.0/financeharness/research.py:24-103
   │  fresh FetchCache · full registry (every mode) · reader paired to backbone
   ▼
Agent.run  messages = [system(base+date+skills catalog+deferred catalog+chaining), *history, user]
   │  loop ─ max_rounds / wall-clock checked at round boundaries          FinanceHarness-0.1.0/financeharness/runtime/agent.py:329-336
   │   ├─ _call_model: proactive compaction → wait_for → classify error
   │   │               (BACKOFF/REGENERATE/COMPACT/FATAL) → escalate on "length"   FinanceHarness-0.1.0/financeharness/runtime/agent.py:151-231
   │   ├─ tool_calls → dispatch_json_args (sequential): parse → lookup → coerce →
   │   │               resolve prev: → validate → handler in event scope →
   │   │               store structured[call_id] + footer                         FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:106-249
   │   └─ no tool_calls → answer → optional grounding re-decode                  FinanceHarness-0.1.0/financeharness/runtime/agent.py:393-414
   ▼
_build_result → finalize(prediction) (citation validation) → trajectory{termination,…}  FinanceHarness-0.1.0/financeharness/runtime/agent.py:428-460
   ▼
session commit iff termination == "answer"                     FinanceHarness-0.1.0/financeharness/service/sessions.py:124-131
```

| Layer | Components | Anchors |
|---|---|---|
| Entry | CLI one-shot / `serve`; FastAPI SSE service; scoping pass | `FinanceHarness-0.1.0/financeharness/cli.py:45-95`, `FinanceHarness-0.1.0/financeharness/service/app.py:204-251`, `FinanceHarness-0.1.0/financeharness/clarify.py:158-183` |
| Orchestration | Loop, recovery wrapper, grounding re-decode, single exit | `FinanceHarness-0.1.0/financeharness/runtime/agent.py:151-460` |
| Dispatch | Never-raise pipeline by design (one gap: a malformed chain index such as `[--1]` raises), arg coercion, reference chaining, ContextVar event scope | `FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:106-249`, `FinanceHarness-0.1.0/financeharness/runtime/arg_coercion.py:86-137`, `FinanceHarness-0.1.0/financeharness/runtime/chaining.py:170-218`, `FinanceHarness-0.1.0/financeharness/runtime/tool_events.py:20-59` |
| Registries | ToolSpec lint, core/deferred tiers, per-run session state, SKILL.md loader | `FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:58-198`, `FinanceHarness-0.1.0/financeharness/runtime/skill_registry.py:115-154` |
| Prompting | Shared principle blocks, three mode variants, catalog assembly | `FinanceHarness-0.1.0/financeharness/runtime/prompts.py:18-216`, `FinanceHarness-0.1.0/financeharness/runtime/modes.py:54-69` |
| Resilience / context | Pure recovery policy, char-heuristic budget, session summarizer, handler retry, layered config | `FinanceHarness-0.1.0/financeharness/runtime/recovery.py:1-148`, `FinanceHarness-0.1.0/financeharness/runtime/context_budget.py:1-67`, `FinanceHarness-0.1.0/financeharness/runtime/retry.py:1-74`, `FinanceHarness-0.1.0/financeharness/runtime/config.py:30-160` |
| Research tools | search (pre-flight validated), visit (fetch → reader LLM), compose_citations, run-local cache | `FinanceHarness-0.1.0/financeharness/tools/research/search.py:77-166`, `FinanceHarness-0.1.0/financeharness/tools/research/visit.py:136-220`, `FinanceHarness-0.1.0/financeharness/tools/research/cache.py:27-73` |
| Data / compute | yfinance equity and market data; calc, DCF, sensitivity, WACC, beta, correlation, VaR | `FinanceHarness-0.1.0/financeharness/tools/research/assembly.py:62-88` |
| Providers | AssistantTurn seam, streaming reassembly, pure quirk adapters, native Gemini, profiles | `FinanceHarness-0.1.0/financeharness/providers/base.py:26-100`, `FinanceHarness-0.1.0/financeharness/providers/client.py:43-233`, `FinanceHarness-0.1.0/financeharness/providers/gemini.py:133-226` |

Audit note: `financeharness/logs/5a9a1c32-…/post_tool_use.json` in the FH tree is output from this session's hook, not repo code.

### 3. Design philosophy, as the code shows it

- **Thin loop, intelligence at named seams.** The loop keeps one shape (call, dispatch, append, repeat). Recovery, chaining, compaction, grounding and citations each plug in at a fixed seam without changing it (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:1-11`). The provider's own parser owns the tool-call wire format (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:8-9`).
- **Tool failure is data, not an exception.** `dispatch` is designed to always return a `DispatchResult`, turning every failure into an `ok=False` markdown message the model can act on (`FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:1-8`). One gap: a chain index such as `[--1]` passes the parser, then raises `ValueError` from `int()` outside any `try` (`FinanceHarness-0.1.0/financeharness/runtime/chaining.py:80-81`, `FinanceHarness-0.1.0/financeharness/runtime/chaining.py:117`). Expected failures (`ToolError`) pass through verbatim; bugs are tagged `handler_exception` (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:33-43`).
- **Hide only noise the model cannot fix.** Transient errors are retried inside handlers. Actionable errors bubble up, because the model "is good at recovering from those and bad at understanding 'the harness retried'" (`FinanceHarness-0.1.0/financeharness/runtime/retry.py:1-7`).
- **Pure decision functions behind I/O shells.** Recovery classification, the token estimate, citation validation and the commit predicate are pure and deterministic (`FinanceHarness-0.1.0/financeharness/runtime/recovery.py:10-11`, `FinanceHarness-0.1.0/financeharness/runtime/context_budget.py:1-7`, `FinanceHarness-0.1.0/financeharness/runtime/citations.py:9`, `FinanceHarness-0.1.0/financeharness/runtime/sessions.py:1-24`).
- **Per-run isolation, no global mutable state.** Each run gets a fresh registry clone, fresh `ToolSessionState`, and meta-tools that are closures over that run's state (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:110-128`, `FinanceHarness-0.1.0/financeharness/runtime/agent.py:273-294`). There is also a fresh `FetchCache` per run (`FinanceHarness-0.1.0/financeharness/research.py:66`).
- **Modes vary the prompt, never the tool surface.** History therefore never references a tool that has disappeared, and one resolver feeds both the advertised mode and the executed one (`FinanceHarness-0.1.0/financeharness/research.py:52-58`).
- **Fail-open for UX, fail-loud for explicit selections.** Scoping, compaction, config and session reads degrade silently (`FinanceHarness-0.1.0/financeharness/clarify.py:108-109`, `FinanceHarness-0.1.0/financeharness/runtime/config.py:146-147`). An explicitly typed profile name is rejected (`FinanceHarness-0.1.0/financeharness/cli.py:181-194`).
- **Honesty lives mostly in prompts.** Prompts are soft and principle-based (`FinanceHarness-0.1.0/financeharness/runtime/prompts.py:62-84`). The only deterministic check is citation-range validation. The claim-to-source check is a same-model self-review (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:258-271`).

### 4. Core mechanisms, ranked by importance to DRF

#### M1. Deterministic compute tier: `calc` plus pass-by-reference payloads (C07, C25, C11)

**What.** Arithmetic never happens in the model's head, and series never round-trip through its context.

**How.**
- `calc` parses with `ast.parse(mode="eval")`. It evaluates only numeric constants, `+ - * / ** % //`, unary `±`, and calls to `abs/round/min/max/sqrt/log/exp` with no keyword arguments (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:28-76`). `|exponent| > 1000` is refused so `10**10**10` cannot block the event loop (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:38-40`, `FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:58-62`). Domain errors become `ToolError` (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:79-92`).
- The tool is core-tier (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:114-122`). The prompt both mandates it and declares its result "already grounded by that call" (`FinanceHarness-0.1.0/financeharness/runtime/prompts.py:65-75`). The docstring cites the failure it prevents: "$37B is a 123% increase from $13B" (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:1-8`).
- Chaining, step by step:
  1. On success the dispatcher stores `structured` under `call_id` and appends the footer `_call_id: X — reference downstream via prev:X.<path>_` (`FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:29-40`, `FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:206-214`).
  2. Before validation, `resolve_references` walks the args and replaces every `prev:` string (`FinanceHarness-0.1.0/financeharness/runtime/chaining.py:186-209`).
  3. The path grammar is `.key`, `[N]` (negative allowed) and `[*]` (map, not nested) (`FinanceHarness-0.1.0/financeharness/runtime/chaining.py:39-89`, `FinanceHarness-0.1.0/financeharness/runtime/chaining.py:125-167`).
  4. Failures name the available keys, the list length or the known ids (`FinanceHarness-0.1.0/financeharness/runtime/chaining.py:96-122`, `FinanceHarness-0.1.0/financeharness/runtime/chaining.py:170-183`).
- Small trick: a lone `["prev:…"]` is unwrapped only for `list[scalar]` fields, so it does not expand to `list[list[float]]` (`FinanceHarness-0.1.0/financeharness/runtime/arg_coercion.py:115-137`).
- Producers design their payloads as chaining surfaces: `bars[*]` (`FinanceHarness-0.1.0/financeharness/tools/data/equity/prices.py:1-7`).

**Why for DRF.** DRF's verifier admits a fact's number only if it appears on its fetched pages (`deerflow_bridge/linear_research.py:2509-2521`). A derived figure (growth %, ratio, implied probability) therefore either fails verification or is laundered. The v3 investigation loop dispatches only `web_search` and `web_fetch` (`deerflow_bridge/linear_research.py:3798-3803`). A reference-fed `calc` whose operands resolve to verified facts or tool payloads gives derived numbers a provenance path by construction.

**Fix before copying:**
- Ids must be opaque and unique per run. When the provider omits an id, FH synthesizes `call_{idx}` per turn (`FinanceHarness-0.1.0/financeharness/providers/client.py:201-205`, `FinanceHarness-0.1.0/financeharness/providers/gemini.py:171-173`), so ids can collide across turns in the chain map.
- Use a structural ref form. Any free-text argument starting with `prev:` is hijacked (`FinanceHarness-0.1.0/financeharness/runtime/chaining.py:33-36`).
- Guard the result. `f"{result:.6g}"` raises `OverflowError` on `10**400`, and `(-8)**0.5` returns a complex number (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:103-111`); both reproduced in memory.
- The exponent guard is post-hoc and bounds only the exponent, so nested powers still run (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:57-62`).

#### M2. Evidence gating: only-read pages are citable, visit has three outcomes, and the reader returns a verdict (C32, C33, C05)

**How.**
- `visit` fetches the page (or hits the cache), then runs a reader LLM that returns `{accessible, summary, evidence}`. `evidence` is supposed to be "one or two short verbatim quotes" (`FinanceHarness-0.1.0/financeharness/tools/research/visit_reader.py:12-23`).
- `add_citation` is called only when `accessible` is true and the summary is non-empty (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:175-194`). Citations are numbered 1-based in visit order, deduped by URL (`FinanceHarness-0.1.0/financeharness/tools/research/cache.py:55-69`).
- Rendering distinguishes three outcomes (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:107-133`):
  - cited: `Source [N]` plus the evidence quote;
  - reader error: "a tool/config issue, not a paywall", so a broken reader does not look like the whole web is blocked;
  - unread: "It's unread, so rely on another source or note the gap."
- A reader transport failure is returned as `reader_error`, distinct from an inaccessible page (`FinanceHarness-0.1.0/financeharness/tools/research/visit_reader.py:71-77`).

**Holes.**
- `evidence` is never checked as a substring of the page text (`FinanceHarness-0.1.0/financeharness/tools/research/visit_reader.py:91-95`).
- Plain-prose reader output is marked accessible, so "I cannot access this page" gets cited (`FinanceHarness-0.1.0/financeharness/tools/research/visit_reader.py:86-90`).
- A missing `accessible` key defaults to `True` (`FinanceHarness-0.1.0/financeharness/tools/research/visit_reader.py:92`).

**Why for DRF.**
- DRF's fetch failure text is only `FETCH_FAILED(reason): try another source.` (`deerflow_bridge/research_gateway.py:3769-3772`). Adopt FH's epistemic wording, and split infrastructure failures from content inaccessibility.
- DRF deliberately selects passages deterministically instead of running a reader LLM (`deerflow_bridge/research_gateway.py:3774-3791`). Keep that. Take only the *verbatim-quote contract*, with a deterministic substring check against the stored page.

#### M3. Pre-research scoping pass (C02)

**How.**
- One 5-hit web snapshot plus one call on the *backbone*, because the small reader "under-asks on subtly ambiguous prompts" (`FinanceHarness-0.1.0/financeharness/clarify.py:168-170`).
- The prompt (`FinanceHarness-0.1.0/financeharness/clarify.py:32-65`):
  - "Strongly prefer proceeding", and record ≤3 default assumptions.
  - It must ask only when no entity is identifiable; otherwise it asks only when interpretations would genuinely diverge.
  - Output is 2–4 option questions with the most likely option first.
  - Every time reference is anchored to today's date, with relative period labels preferred.
- Normalization caps the counts and turns "insufficient but no usable questions" into sufficient (`FinanceHarness-0.1.0/financeharness/clarify.py:85-109`). Every failure is fail-open (`FinanceHarness-0.1.0/financeharness/clarify.py:113-116`, `FinanceHarness-0.1.0/financeharness/clarify.py:141-155`).

**Gap.** Only *answered* questions reach the run (`FinanceHarness-0.1.0/financeharness/clarify.py:233-242`, `FinanceHarness-0.1.0/financeharness/research.py:95-97`). The scoper's assumptions are returned to the client and then dropped.

**Why for DRF.** Forecast questions are ambiguous exactly where calibration depends on them: what counts as "wins", the resolution source, the horizon. In DRF, resolution criteria first appear as LLM output at forecast extraction (`backend/app/services/forecast_extractor.py:47-56`), and grep finds no `resolution_criteria` in `deerflow_bridge/`. Transplant the pass as a pre-RESEARCH brief contract whose assumptions are *persisted*. Extend the must-ask trigger to "no resolvable criterion".

#### M4. Epistemic prompt blocks shared across modes (C27)

**How.** The shared blocks are composed into every variant, except that the analytical variant swaps `_HOW_YOU_RESEARCH` for `_HOW_YOU_ANALYZE` (`FinanceHarness-0.1.0/financeharness/runtime/prompts.py:132-154`):
- `_HOW_YOU_RESEARCH`: "search results are leads, not evidence"; "where accounts disagree, the disagreement is often the finding" (`FinanceHarness-0.1.0/financeharness/runtime/prompts.py:18-38`).
- `_GROUNDING` (`FinanceHarness-0.1.0/financeharness/runtime/prompts.py:62-84`):
  - "a word in brackets like `[search]` is not a citation";
  - a snippet-only fact is "not yet grounded";
  - separate what a source *reports* from what it *projects*;
  - "A clean qualitative statement beats a precise-looking number you can't stand behind."
- Skills restate these ideas as domain rules: "the disagreement is the finding — surface it rather than averaging it away" (`FinanceHarness-0.1.0/financeharness/skills/equity-deep-dive/SKILL.md:45-54`); "dispersion … is itself the signal" (`FinanceHarness-0.1.0/financeharness/skills/consensus-check/SKILL.md:26-33`); "a bad peer set makes a precise-looking range meaningless" (`FinanceHarness-0.1.0/financeharness/skills/relative-valuation/SKILL.md:31-38`).
- The estimates tool's description tells the model its figures are "not reported results" (`FinanceHarness-0.1.0/financeharness/tools/data/equity/estimates.py:31-38`).

**Why for DRF.** DRF has VERIFIED vs REPORTED (`deerflow_bridge/linear_research.py:243`) and a contested-facts channel (`deerflow_bridge/linear_research.py:6106`). The missing axis is reported vs projected. Analyst forecasts laundered into base rates are the forecasting-specific failure. FH enforces this only in prose. DRF should make it a typed field on quantitative facts.

#### M5. Never-raise typed dispatch with schema-driven argument repair (C34, C01)

**How.** The pipeline runs these steps, each failure producing an `ok=False` result of a named kind:
1. `json.loads` fails → `args_not_json`, keeping `{_raw}`.
2. Registry miss → `unknown_tool`, listing the core tools and a `load_tool` hint.
3. `coerce_stringified_json` and `coerce_wrapped_ref` repair arguments.
4. Chain resolution fails → `chain_resolution` with a failures list. The one gap: an index such as `[--1]` passes the parser because `'--1'.lstrip('-').isdigit()` is true, then `int()` raises `ValueError` outside dispatch's `try` (`FinanceHarness-0.1.0/financeharness/runtime/chaining.py:80-81`, `FinanceHarness-0.1.0/financeharness/runtime/chaining.py:117`, `FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:139-142`).
5. Pydantic validation fails → `schema_validation`, rendered as up to 5 path-aware lines (`FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:43-54`).
6. The handler raises → `handler_response_invalid`, `tool_error` (verbatim) or `handler_exception`.

(`FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:106-249`)

- Coercion re-parses a JSON string only when the schema field is a container and the string starts with `[` or `{`. Unparseable values pass through so Pydantic reports them (`FinanceHarness-0.1.0/financeharness/runtime/arg_coercion.py:86-112`).
- Tool-local repair is driven by measured failures. "~89% of visit failures were malformed multi-URL args", so `visit` splits lone strings, JSON-stringified arrays and comma-joined runs (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:38-89`).
- `tool_log` keeps the *raw* pre-resolution args, so `prev:` references are logged as written rather than expanded (`FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:81-90`).

**Why for DRF.** ReportAgent regex-parses `<tool_call>` JSON (`backend/app/services/report_agent.py:8948-9003`). It dispatches with an if/elif chain whose `parameters.get(...)` defaults hide bad parameters (`backend/app/services/report_agent.py:8776-8802`). Pydantic request models plus typed error kinds turn silently defaulted calls into correctable observations, and give countable failure kinds for the completion health gate.

#### M6. Single exit, termination taxonomy, no-poison commit (C19, C34)

**How.**
- Every path funnels into `_build_result`, which returns one uniform dict with `termination` in {answer, max_rounds, timeout, error, length…} (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:329-350`, `FinanceHarness-0.1.0/financeharness/runtime/agent.py:393-399`, `FinanceHarness-0.1.0/financeharness/runtime/agent.py:428-460`). An injected `finalize` hook runs there at most once, and only on a non-empty prediction, which keeps the loop citation-agnostic (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:109-112`, `FinanceHarness-0.1.0/financeharness/runtime/agent.py:446-447`).
- Downstream code keys off `termination`:
  - session commit only for `answer`, system messages stripped (`FinanceHarness-0.1.0/financeharness/runtime/sessions.py:17-24`, `FinanceHarness-0.1.0/financeharness/service/sessions.py:124-131`);
  - CLI exit code 0 only for `answer` (`FinanceHarness-0.1.0/financeharness/cli.py:64-65`).

**Trap.** A `stop` turn with empty content still counts as `answer`, and the CLI then prints "(no answer produced)" and exits 0 (`FinanceHarness-0.1.0/financeharness/cli.py:64-65`).

**Why for DRF.** For ledger and stage commits, promote an artifact only when it has a clean terminal status *and* a non-empty payload.

#### M7. Search pre-flight readability check and serialized native parsing (C17)

**How.**
- `search` over-fetches 2×, then pre-fetches up to 16 candidates with a single-attempt 8 s `quick_fetch` under `Semaphore(8)`. It keeps a page only if `ok` and it has ≥200 extracted chars, and warms the cache with the page text so a later `visit` is a cache hit (`FinanceHarness-0.1.0/financeharness/tools/research/search.py:27-35`, `FinanceHarness-0.1.0/financeharness/tools/research/search.py:77-96`, `FinanceHarness-0.1.0/financeharness/tools/research/visit_fetch.py:104-111`).
- All lxml and pdfplumber parsing runs on a single-worker pool with a 25 s timeout, because these native parsers "corrupt the heap when run in parallel threads" (`FinanceHarness-0.1.0/financeharness/tools/research/visit_fetch.py:30-57`).

**Bugs.**
- `_validate` checks `candidates[:16]`, and one query already supplies up to 16 hits (`FinanceHarness-0.1.0/financeharness/tools/research/search.py:84`, `FinanceHarness-0.1.0/financeharness/tools/research/search.py:116`). In a multi-query batch, later queries are never validated and are dropped unless zero pages validate.
- The fallback returns unvalidated hits, while the description still tells the model they were "pre-checked" (`FinanceHarness-0.1.0/financeharness/tools/research/search.py:37-41`, `FinanceHarness-0.1.0/financeharness/tools/research/search.py:147-148`).
- Every fetch failure, including 403s and empty extraction, is tagged retryable, and `http_fetch` tries it up to 3 times in all (`FinanceHarness-0.1.0/financeharness/tools/research/visit_fetch.py:48`, `FinanceHarness-0.1.0/financeharness/tools/research/visit_fetch.py:80-101`, `FinanceHarness-0.1.0/financeharness/tools/research/visit_fetch.py:114-129`).

**Why for DRF.** `web_search_impl` returns raw hits (`deerflow_bridge/search_tools.py:564-568`), so blocked pages are discovered only after a paid `web_fetch`. Reuse `_failure_reason` as the keep/drop test (`deerflow_bridge/research_gateway.py:3750-3767`), interleave candidates across queries, and label fallback hits as unverified. The DRF direct-fetch fallback extracts via `asyncio.to_thread` (`deerflow_bridge/cached_fetch.py:219`); if that extractor is lxml-backed, parallel lanes face the same heap-corruption risk.

#### M8. Pure model-call recovery policy with bounded `max_tokens` escalation (C15)

**How.** `classify_model_error` (`FinanceHarness-0.1.0/financeharness/runtime/recovery.py:58-80`) maps errors as follows:

| Error | Action |
|---|---|
| 400 with an overflow signature | COMPACT |
| Any other 400 | REGENERATE: identical request, re-rolled at temperature > 0, ≤3 times |
| Transient status, or a transient SDK class name in the MRO | BACKOFF: ≤10 retries, jittered exponential |
| Anything else | FATAL |

- `status_of` reads `.status_code`, `.status` or `.code`, and the first int wins (`FinanceHarness-0.1.0/financeharness/runtime/retry.py:22-35`).
- On `finish_reason=="length"`, the budget becomes `min(cur*max(factor,2), ceiling)`, at most 3 times (16384→32768→65536). The `max(…,2)` guard stops a factor of 1 from looping forever (`FinanceHarness-0.1.0/financeharness/runtime/recovery.py:83-92`, `FinanceHarness-0.1.0/financeharness/runtime/agent.py:218-231`).
- Each call is wrapped in `asyncio.wait_for`, so a hang becomes BACKOFF (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:181-186`).

**Why for DRF.** `llm_client` raises on empty content with `finish_reason=length` and tells the operator to raise `max_tokens` (`backend/app/utils/llm_client.py:929-938`). Bounded automatic escalation belongs there, for ontology, sim config and the report spine. v3 already widens once (`deerflow_bridge/linear_research.py:5660-5666`). DRF's classifier is already richer than FH's (`deerflow_bridge/research_gateway.py:239-244`, `deerflow_bridge/research_gateway.py:314-352`); the new ideas are the REGENERATE category and keeping the policy pure.

**Do not inherit:**
- the narrow overflow list, which misses "prompt is too long" (`FinanceHarness-0.1.0/financeharness/runtime/recovery.py:25-30`);
- the unretried `error` finish reason (`FinanceHarness-0.1.0/financeharness/providers/gemini.py:209-221`);
- defaulting a missing finish reason to `stop` (`FinanceHarness-0.1.0/financeharness/providers/client.py:224-225`);
- checking the wall clock only between rounds (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:329-336`). A single round can take 1800 s × 11 attempts (`FinanceHarness-0.1.0/financeharness/runtime/config.py:45-50`).

#### M9. Compaction on a per-call copy with output reservation (C28)

**How.**
- Before every call, if `ceil(chars/4) + 4·msgs > window − max_tokens − buffer`, old role=tool bodies are elided and the last 4 are kept (`FinanceHarness-0.1.0/financeharness/runtime/context_budget.py:14-67`, `FinanceHarness-0.1.0/financeharness/runtime/recovery.py:114-148`).
- The elided list is only the local `work` copy. The canonical `messages` keep full outputs for the trajectory (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:163-179`).
- Escalated `max_tokens` feeds the threshold, so escalation tightens the prompt budget.

**Weaknesses.**
- The `tools=` schemas are not counted (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:169-174`).
- Loaded skill recipes are ordinary tool messages and get elided too.
- The elision boundary is recomputed every call, which is cache-hostile.

**Why for DRF.** Apply this to ReportAgent and chat loops, but make elision sticky and monotonic so provider prompt caching survives, and pin brief and recipe messages. DRF's estimator is also chars/4, and its own comment admits it is optimistic for CJK (`backend/app/utils/token_budget.py:26-27`, `backend/app/utils/token_budget.py:39-47`).

#### M10. Vendor-data hygiene: NaN guard, producer-side unit normalization, distrust of vendor row order (C44)

**How.**
- `is_num` = `numbers.Real`, not bool, `v == v` (`FinanceHarness-0.1.0/financeharness/tools/data/equity/common.py:36-53`).
- NaN bars are skipped so `int(NaN)` cannot crash (`FinanceHarness-0.1.0/financeharness/tools/data/equity/prices.py:162-167`).
- NaN is kept out of JSON payloads (`FinanceHarness-0.1.0/financeharness/tools/data/equity/estimates.py:141-150`).
- `debtToEquity` and `dividendYield` are ÷100 at the producer, and PEG falls back to a renamed field (`FinanceHarness-0.1.0/financeharness/tools/data/equity/ratios.py:63-88`).
- The recommendation row is selected by `period=="0m"`, not by position (`FinanceHarness-0.1.0/financeharness/tools/data/equity/estimates.py:69-76`).

**Inconsistencies.**
- `fundamentals` filters only `is not None`, so NaN leaks through (`FinanceHarness-0.1.0/financeharness/tools/data/equity/fundamentals.py:139-143`).
- `currentPrice or regularMarketPrice` lets NaN through because NaN is truthy (`FinanceHarness-0.1.0/financeharness/tools/data/equity/comps.py:127`).
- The ÷100 is unconditional, with no magnitude check.

**Why for DRF.** Use one guard at every ingestion boundary (Polymarket, quantitative facts, sim metrics) plus `allow_nan=False` on handoff artifacts.

#### M11. Market primitives for base rates (C24, value 2, one refutation)

**How.**
- Realized volatility uses log returns with sample variance, annualized by bars per year ({1d:252, 5d:50, 1wk:52, 1mo:12}), and the factor is shown (`FinanceHarness-0.1.0/financeharness/tools/data/equity/prices.py:22-24`, `FinanceHarness-0.1.0/financeharness/tools/data/equity/prices.py:81-94`).
- Technicals are "named canon only" with no interpretive labels (`FinanceHarness-0.1.0/financeharness/tools/data/equity/prices.py:1-7`).
- Correlation runs over one common window with an honest `n_obs`, and returns `None` for constant series (`FinanceHarness-0.1.0/financeharness/tools/compute/risk/correlation.py:53-78`).
- VaR uses √h vol scaling, linear drift scaling, and is clamped at ≥0 (`FinanceHarness-0.1.0/financeharness/tools/compute/risk/var.py:51-85`).

**Flaws for DRF use.**
- Alignment is by tail count, not by date (`FinanceHarness-0.1.0/financeharness/tools/compute/risk/returns.py:16-22`).
- Quotes carry no as-of date (`FinanceHarness-0.1.0/financeharness/tools/data/market/indices.py:47-51`).
- There is no point-in-time retrieval.

A DRF threshold-probability tool needs dated series and an as-of cutoff.

#### M12. Code does the math and the model supplies judgment: blank-not-fudge, all-or-none, show-your-work (C25)

**How.**
- Comps: the model picks the peers and the tool does the arithmetic (`FinanceHarness-0.1.0/financeharness/tools/data/equity/comps.py:1-16`). Peer multiples are filtered to >0 before the medians are taken, and non-positive implied values are dropped (`FinanceHarness-0.1.0/financeharness/tools/data/equity/comps.py:89-95`, `FinanceHarness-0.1.0/financeharness/tools/data/equity/comps.py:163-191`).
- The DCF validator encodes domain impossibilities, e.g. `g < r` or "the perpetuity is undefined" (`FinanceHarness-0.1.0/financeharness/tools/compute/valuation/dcf.py:88-104`).
- The sensitivity grid reuses that validator per cell. Invalid cells become `None` and are excluded from low/high, "never fudged" (`FinanceHarness-0.1.0/financeharness/tools/compute/valuation/dcf_sensitivity.py:102-154`).
- WACC requires the debt trio to be all set or all unset (`FinanceHarness-0.1.0/financeharness/tools/compute/valuation/wacc.py:65-77`), and renders formulas with the values substituted in (`FinanceHarness-0.1.0/financeharness/tools/compute/valuation/wacc.py:119-132`).

**Why for DRF.** The report spine should work the same way. The LLM emits drivers, reference class and blend choices as structured fields. Code computes normalization, blends and anchor deltas, renders "shown work", and blanks invalid sensitivity cells rather than coercing them.

#### M13. Provider seam (C41, C23)

**How.**
- `AssistantTurn(content, tool_calls, finish_reason, native)` carries no reasoning text, which streams live through the `on_delta` callback; only opaque provider-native items (such as encrypted OpenAI Responses reasoning items) ride in history under `_native` (`FinanceHarness-0.1.0/financeharness/providers/base.py:42-75`).
- `ToolCall.extra` round-trips opaque state such as Gemini's `thought_signature` (`FinanceHarness-0.1.0/financeharness/providers/base.py:26-39`), and `_`-prefixed keys are stripped on the wire (`FinanceHarness-0.1.0/financeharness/providers/client.py:57-62`).
- Streaming uses raw `create(stream=True)` because the SDK beta helper rejects non-strict tools. Deltas are reassembled into the same `ChatCompletion` shape, so the `length` check does not depend on the path (`FinanceHarness-0.1.0/financeharness/providers/client.py:100-120`, `FinanceHarness-0.1.0/financeharness/providers/client.py:187-233`).
- Quirks are pure `kwargs→kwargs` adapters selected by name (`FinanceHarness-0.1.0/financeharness/providers/adapters/__init__.py:21-37`, `FinanceHarness-0.1.0/financeharness/providers/adapters/openai.py:13-26`).

**Why for DRF.** DRF keeps quirks as methods (`backend/app/utils/llm_client.py:842`, `backend/app/utils/llm_client.py:857`) with capabilities in `PROVIDER_META` (`backend/app/config.py:849`). Pure named adapters referenced from `PROVIDER_META` would make each quirk testable offline. Validate adapter names at startup; FH silently degrades an unknown name to identity (`FinanceHarness-0.1.0/financeharness/providers/adapters/__init__.py:29-37`).

#### M14. Progressive disclosure and skills (C45, value 2)

**How.**
- `ToolSpec.__post_init__` lints wire names against `^[a-zA-Z0-9_-]+$` and requires descriptions of ≥30 chars, because "catalog routing needs signal" (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:79-89`).
- Deferred tools appear as sorted catalog lines (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:102-107`, `FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:150-153`). `load_tool` marks them loaded, and they become visible from the next call (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:167-198`, `FinanceHarness-0.1.0/financeharness/tools/core/load_tool.py:41-72`).
- `load_skill` auto-loads a skill's `requires_tools` and silently skips unknown ones (`FinanceHarness-0.1.0/financeharness/tools/core/load_skill.py:47-76`).
- Bundled skills load strictly; user skills load leniently with a silent skip (`FinanceHarness-0.1.0/financeharness/runtime/skill_registry.py:132-154`).
- A dotted→underscored name fallback absorbs an open-weight model quirk (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:130-139`).

**Weaknesses.**
- Deferral is not enforced: dispatch looks tools up in the whole registry (`FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:119`).
- Every load changes `tools=`, which breaks provider prompt-cache prefixes.
- `./skills` is auto-discovered from the CWD, which is a prompt-injection surface (`FinanceHarness-0.1.0/financeharness/tools/research/assembly.py:91-102`).

**Relevance.** Mainly to drf2.

#### M15. Live events: ContextVar scope, closed vocabulary, authoritative final frame (C46, value 2, one refutation)

**How.**
- The dispatcher wraps each handler in `tool_event_scope`, so handlers call `emit_tool_progress` or `emit_tool_event` without an emitter in their signature. These are no-ops outside a scope (`FinanceHarness-0.1.0/financeharness/runtime/tool_events.py:20-59`, `FinanceHarness-0.1.0/financeharness/runtime/dispatch.py:172-174`).
- `sse_frame` raises on any event not in `EVENT_TYPES` (`FinanceHarness-0.1.0/financeharness/service/events.py:49-82`).
- A `: ping` heartbeat is sent every 10 s (`FinanceHarness-0.1.0/financeharness/service/app.py:38-58`).
- Streamed tokens are advisory; the terminal `done` carries the same trajectory as the sync endpoint (`FinanceHarness-0.1.0/financeharness/service/app.py:204-251`).
- For audit, a head+tail excerpt keeps end-of-output figures (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:57-78`).

**Caution.** Raising inside the live generator kills the stream. DRF should assert event names in tests rather than at runtime. DRF currently derives liveness from heartbeats (`frontend/src/utils/runVitals.js:14-17`).

#### M16. Ops hygiene: readiness probe, strict explicit selection, safe ids, headless CLI (C43, C38, C47)

- `/health` probes `/models` with auth for both the backbone and its paired reader (`FinanceHarness-0.1.0/financeharness/service/app.py:148-190`). For DRF, use a 1-token completion instead, since only a real completion reveals quota walls.
- A typo'd `--profile` or request `profile` is rejected with the valid names listed (`FinanceHarness-0.1.0/financeharness/cli.py:181-194`, `FinanceHarness-0.1.0/financeharness/service/app.py:125-145`).
- Session ids are checked against `\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z` before any path join, and writes use tmp + `os.replace` (`FinanceHarness-0.1.0/financeharness/service/sessions.py:28-35`, `FinanceHarness-0.1.0/financeharness/service/sessions.py:95-101`).
- Every runtime dependency is declared, with two console-script aliases (`FinanceHarness-0.1.0/pyproject.toml:1-24`).

### 5. Commodity, weak or buggy: do not copy

| Item | Problem | Anchor |
|---|---|---|
| `extract_json_obj` | Greedy `\{.*\}` with no brace balancing and no repair retry. DRF v3's repair retry is better. | `FinanceHarness-0.1.0/financeharness/runtime/jsonutil.py:9-27` |
| Citation orphan stripper | Bare `\[\d+\]` deletes years: "In [2024] it rose" became "In it rose" (reproduced). | `FinanceHarness-0.1.0/financeharness/runtime/citations.py:27`, `FinanceHarness-0.1.0/financeharness/runtime/citations.py:55-75` |
| References-heading truncation | Any heading starting "References" cuts the rest of the report (reproduced with "## References to prior guidance"). | `FinanceHarness-0.1.0/financeharness/runtime/citations.py:17-20` |
| `calc` output | Float `.6g` formatting overflows on huge ints; complex results are possible; nested powers bypass the guard. | `FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:52-63`, `FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:103-111` |
| Search validation | Only the first 16 candidates are validated (at default settings, just the first query's results); the fallback is unlabelled. | `FinanceHarness-0.1.0/financeharness/tools/research/search.py:84`, `FinanceHarness-0.1.0/financeharness/tools/research/search.py:147-148` |
| Fetch retry | Every failure is "retryable"; no 404/410 check; no SSRF guard (DRF has `_host_is_public`, `deerflow_bridge/cached_fetch.py:136`). | `FinanceHarness-0.1.0/financeharness/tools/research/visit_fetch.py:70-129` |
| Parse pool | `wait_for` cancels the await but not the thread, so a hung parse blocks the only worker. | `FinanceHarness-0.1.0/financeharness/tools/research/visit_fetch.py:52-57` |
| Reader fallbacks | Prose counts as accessible; a missing verdict defaults to True; quotes are never verified. | `FinanceHarness-0.1.0/financeharness/tools/research/visit_reader.py:79-95` |
| Grounding re-decode | Bypasses `_call_model`: no wall-clock timeout wrapper, no recovery retries, no `finish_reason` check, so a truncated rewrite can replace a complete draft. | `FinanceHarness-0.1.0/financeharness/runtime/agent.py:233-256` |
| Config "never raises" | Type-invalid values raise from `RuntimeConfig(**merged)` outside the `try`; bad env values and file errors are silent. | `FinanceHarness-0.1.0/financeharness/runtime/config.py:140-160` |
| Profile loading | Malformed profiles are skipped silently, so `profiles[_DEFAULT]` can `KeyError`; the merge is shallow per profile. | `FinanceHarness-0.1.0/financeharness/providers/profiles.py:173-191`, `FinanceHarness-0.1.0/financeharness/providers/profiles.py:224-226` |
| yfinance transient classifier | `"rate" in text` matches "generate" and "separate", so non-transient errors get retried. | `FinanceHarness-0.1.0/financeharness/tools/data/equity/common.py:56-63` |
| Frontmatter split | `split('---', 2)` breaks on a `---` inside a YAML value (reproduced). | `FinanceHarness-0.1.0/financeharness/runtime/frontmatter.py:28-42` |
| Beta docs | The description says to take the benchmark series from `data.market.indices`, which returns only level and change. | `FinanceHarness-0.1.0/financeharness/tools/compute/risk/beta.py:19-25`, `FinanceHarness-0.1.0/financeharness/tools/data/market/indices.py:47-51` |
| DCF sensitivity | Promises a "bear/base/bull range" but returns only min/max. | `FinanceHarness-0.1.0/financeharness/tools/compute/valuation/dcf_sensitivity.py:1-9`, `FinanceHarness-0.1.0/financeharness/tools/compute/valuation/dcf_sensitivity.py:151-153` |
| Mode defaults | An unknown name maps to `auto`; an omitted name maps to `research`. | `FinanceHarness-0.1.0/financeharness/runtime/modes.py:54-69` |
| Dead flag | `-p/--print` (dest `oneshot`) is parsed and never read. | `FinanceHarness-0.1.0/financeharness/cli.py:133-141` |
| No cost accounting | `AssistantTurn` has no usage field; there are no run-level token or cost budgets (only a per-call `max_tokens`). | `FinanceHarness-0.1.0/financeharness/providers/base.py:42-58`, `FinanceHarness-0.1.0/financeharness/runtime/config.py:42-50` |
| Non-atomic trajectory save | Plain `write_text`. | `FinanceHarness-0.1.0/financeharness/research.py:106-111` |
| Search backend | ddgs with no timeout, retry or date metadata. | `FinanceHarness-0.1.0/financeharness/tools/research/search_backends.py:16-63` |

### 6. Lessons recorded in code comments (no tests or changelog ship)

1. About 89% of visit failures were malformed multi-URL arguments, which motivated shape repair before validation (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:59-65`).
2. Native parsers corrupt the heap when run in parallel threads, so parsing is serialized (`FinanceHarness-0.1.0/financeharness/tools/research/visit_fetch.py:30-35`).
3. A reader failure looked like a paywall, so it now gets its own branch (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:115-123`).
4. A failed read is not evidence (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:126-131`).
5. The grounding review clobbered no-tool answers, so it is skipped when `tool_log` is empty (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:400-408`).
6. The small reader under-asked when scoping, so scoping moved to the backbone (`FinanceHarness-0.1.0/financeharness/clarify.py:168-170`).
7. The SDK's beta `.stream()` rejects non-strict tools, so streaming uses the raw iterator plus reassembly (`FinanceHarness-0.1.0/financeharness/providers/client.py:110-120`).
8. Gemini's OpenAI-compatible endpoint caused streamed tool-calling stalls, so FH uses the native SDK, and `thought_signature` must be echoed back (`FinanceHarness-0.1.0/financeharness/providers/gemini.py:1-15`, `FinanceHarness-0.1.0/financeharness/providers/client.py:168-175`).
9. Safety-blocked or empty Gemini turns map to `error`, not `stop` (`FinanceHarness-0.1.0/financeharness/providers/gemini.py:209-221`).
10. A typo'd profile silently ran on the wrong model, so explicit selections are validated (`FinanceHarness-0.1.0/financeharness/cli.py:181-184`).
11. Open-weight models emit dotted tool names, which the registry now maps to wire names (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:130-139`).
12. `10**10**10` could block the event loop, so exponents are bounded (`FinanceHarness-0.1.0/financeharness/tools/compute/arithmetic.py:38-40`).
13. yfinance drifted on NaN bars and on percent-vs-fraction fields (`FinanceHarness-0.1.0/financeharness/tools/data/equity/prices.py:162-163`, `FinanceHarness-0.1.0/financeharness/tools/data/equity/ratios.py:66`, `FinanceHarness-0.1.0/financeharness/tools/data/equity/ratios.py:83-84`).
14. SSE idle timeouts during silent tool calls led to the heartbeat (`FinanceHarness-0.1.0/financeharness/service/app.py:38-42`).
15. Models echoed the harness's own instruction ("appends references"), so a leak regex strips it. The fix creates a new failure: a `.]` residue (`FinanceHarness-0.1.0/financeharness/runtime/citations.py:21-26`).
16. Models wrote `[search]` as a citation, so a prompt rule forbids it (`FinanceHarness-0.1.0/financeharness/runtime/prompts.py:67-70`).
17. The comps table was being padded from memory, so the tool now surfaces grounded per-peer fundamentals (`FinanceHarness-0.1.0/financeharness/tools/data/equity/comps.py:12-15`).

### 7. Paper claims vs code reality

| Paper (2607.27853) | Released code | Anchor |
|---|---|---|
| Point-in-time search sandbox (FAISS, 100M+ articles, cutoff-filtered) | Live DuckDuckGo only. No `cutoff`, `as_of`, date filter or FAISS anywhere (grep returned nothing). | `FinanceHarness-0.1.0/financeharness/tools/research/search_backends.py:16-63` |
| Core tier includes a `finalize` tool | Finalize is an Agent hook, not a tool. The core set is search, visit, compose_citations, calc, update_plan, load_tool, load_skill. | `FinanceHarness-0.1.0/financeharness/runtime/agent.py:441-447`, `FinanceHarness-0.1.0/README.md:121-127` |
| Extension tier of MCP/CLI connectors | No MCP code (grep returned nothing). | `FinanceHarness-0.1.0/financeharness/tools/research/assembly.py:62-88` |
| "Citation retrofit when a draft omits them" | The finalizer only strips and appends; nothing retrofits. | `FinanceHarness-0.1.0/financeharness/runtime/citations.py:42-96` |
| Search-budget caps, run-level budgets | Only round, wall-clock and retry caps; no search, token or cost budget. | `FinanceHarness-0.1.0/financeharness/runtime/config.py:42-50` |
| URL pre-fetch validation cuts visit errors from 39.4% to 2.1% | Pre-flight validation exists but carries the first-query truncation bug. The code's own statistic concerns a different failure (89% malformed arguments). | `FinanceHarness-0.1.0/financeharness/tools/research/search.py:77-96`, `FinanceHarness-0.1.0/financeharness/tools/research/visit.py:59-65` |
| Case study loads `industry-analysis` | Only 5 skills ship (consensus-check, dcf-valuation, equity-deep-dive, relative-valuation, ticker-snapshot). | `FinanceHarness-0.1.0/README.md:141-147` |
| GRPO fine-tuning (+0.4, below the ~0.8 SE) | No training code in the repo. | `FinanceHarness-0.1.0/pyproject.toml:7-19` |
| Grounding review softens claims it cannot tie to sources | Same-model rewrite; no diff check, no truncation check. | `FinanceHarness-0.1.0/financeharness/runtime/agent.py:233-271` |

Paper-internal issues: the 44.9% (Opus-5) figure is untabulated; the text says both 23 and 17 baselines; the ceiling is given as "below 40%" in some places and "below 45%" in others; there is one run per question; and the judge is from the same model family as the generator. The empirical result most useful to DRF: harness engineering raised pre-cutoff evidence scores by +9.6 but post-cutoff (forward-looking) scores by only +3.1, and backbone choice spread scores more than scaffold choice. Expect research-engine gains to appear in evidence quality rather than in Brier score.

### 8. What DRF should take, and what not

**Take (reimplement; do not copy code):**

| Candidate | FH source | DRF landing | Required adaptation |
|---|---|---|---|
| **C07** compute tier | M1 calc and chaining | v3 tools (`deerflow_bridge/linear_research.py:3798-3803`) and ReportAgent | Opaque unique ids; `{"$ref":…}` form; provenance tag on resolved values; derived-number ledger whose operands must be page-verified or come from a tool |
| **C11** figure provenance | Head+tail audit trace (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:57-78`); a tool figure is "already grounded by that call" (`FinanceHarness-0.1.0/financeharness/runtime/prompts.py:65-67`) | Report appendix and lint | A persistent figure→artifact map, not a UI-only trace |
| **C25** spine arithmetic | M12 | Report spine and forecast extractor | LLM emits structured judgment inputs; code computes, shows its work, blanks invalid cells |
| **C02** brief scoping | M3 | New pre-RESEARCH step in `pipeline_orchestrator` | Persist assumptions into the brief contract; add a resolution-criteria must-ask trigger; ask only in interactive UI |
| **C27** epistemic discipline | M4 | Shared prompt blocks for research and report; typed `reported/projected/estimate` field on facts | Enforce deterministically, not just in prose |
| **C32** verbatim evidence quotes | M2 reader contract | Quantitative facts and dossier | Substring check against stored page text; no reader LLM needed |
| **C33** grounding finalization | M2 gating plus finalizer stats | Research quality telemetry and publication gates | Namespaced `[S#]` (already present: `_build_sources_index` renders bare positional `[S<n>]` markers, `backend/app/services/report_agent.py:2215-2224`) avoids the year bug; any attribute-or-soften pass must clear the v3 adoption guard (`deerflow_bridge/linear_research.py:5378-5382`) and run before `remove_dangling_attributions` (`backend/app/services/report_lint.py:422`) |
| **C05** typed failure sentinels | Three-way visit outcome | `_fetch_failed` wording (`deerflow_bridge/research_gateway.py:3769-3772`) | Separate infrastructure/auth/circuit-open failures from content inaccessibility |
| **C34 / C01** tool boundary | M5 | ReportAgent (`backend/app/services/report_agent.py:8776-8802`, `backend/app/services/report_agent.py:8948-9003`), MCP servers | Typed error kinds counted in the health gate |
| **C19** commit discipline | M6 no-poison commit | Forecast ledger and stage promotion | Also require a non-empty payload, which FH does not |
| **C17** retrieval hardening | M7 | `web_search_impl` (`deerflow_bridge/search_tools.py:564-568`), `cached_fetch` | Interleave across queries; reuse `_failure_reason`; label unverified fallback hits; serialized parser worker |
| **C15** recovery | M8 | `llm_client.chat` (`backend/app/utils/llm_client.py:431-477`; empty-content raise in `_chat_openai`, `backend/app/utils/llm_client.py:929-938`) | Bounded ×2 escalation; REGENERATE category; missing finish reason treated as `error` |
| **C28** compaction | M9 | ReportAgent and chat loops | Sticky, monotonic elision; pinned messages; count schemas; CJK-aware estimator |
| **C44** fail-closed data guards | M10 | Every ingestion boundary and artifact write | Consistent guard; reject ±Inf; `allow_nan=False` |
| **C41 / C23** transport and capability registry | M13 | `llm_client` / `PROVIDER_META` | Fail closed on unknown adapter names; keep usage accounting |
| **C24** base-rate tools (value 2) | M11 volatility primitive | Research and report quant tier | Date-joined series; point-in-time as-of; lognormal P(S_T > K) added |
| **C43 / C38 / C47** | M16 | Pre-launch stage probes; API id validation; headless `drf run` | Completion probe instead of `/models`; exit code keyed to the health gate |
| **C45 / C46** (value 2) | M14, M15 | drf2 driver; research live-sources rail | Enforce loaded-ness if telemetry depends on it; append-only schema growth to keep the cache; do not kill live streams on an unknown event |
| **C13** strict config | FH as a *counter-example* | `backend/app/config.py` | Do the opposite of FH's silent fallbacks: log or refuse unknown and invalid knobs |

**Do not take:**
- **The reader-LLM per page.** It adds cost and an extra laundering step. DRF's deterministic passage selection plus number verification is stronger (`deerflow_bridge/research_gateway.py:3774-3791`, `deerflow_bridge/linear_research.py:2509-2521`).
- **The same-model grounding rewrite as an authority.** DRF's deterministic lint and gates should stay the final judge.
- **FH's bare `[N]` citation regexes, `extract_json_obj`, ddgs backend, or `FetchCache`.** DRF's `SourceLedger` already does canonical-URL dedup with ids that are stable across resumes (`deerflow_bridge/research_gateway.py:2371-2376`).
- **Cancel-on-disconnect.** DRF's multi-hour subprocess pipelines must survive client disconnects.
- **CWD skill auto-discovery**, and silent lenient skill skips.
- **FH's recovery classifier as-is.** DRF's is richer (`deerflow_bridge/research_gateway.py:314-352`). Borrow only REGENERATE and the escalation guard.
- **The chars/4 estimator unchanged**, given DRF's bilingual output (`backend/app/utils/token_budget.py:26-27`).
- **yfinance-backed equity tools as a data source.** They have no point-in-time or as-of capability (`FinanceHarness-0.1.0/financeharness/tools/data/market/quotes.py:13-33`), which would leak future information into DRF backtests and golden replays. Any market or macro tool DRF adds needs as-of dates and a cutoff (C06).

## StockAgent

`Stockagent-main` is the code for Zhang et al., "When AI Meets Finance (StockAgent)" (ACM TIST; arXiv 2407.18957). It is about 1,600 lines of Python. There are no tests, no VCS history and **no license file**, so DRF may reimplement its ideas but must not copy its code.

### 1. Essence

StockAgent is a small discrete-time market simulation driven by LLM agents. Python holds all the state: cash, holdings, loans, order books, prices and the calendar. Each agent calls the LLM at only four typed decision points per day, and three of them return a single JSON object (loan; order, one per session, three sessions; next-day intent), while the fourth is a free-text forum post (Stockagent-main/main.py:139-189). Two ideas make it worth studying.

1. **The "Secretary".** Despite its LLM-shaped constructor, this is a deterministic validator. It checks every decision against the agent's live state (cash, holdings, credit cap). On failure it returns a plain-English reason that names the broken constraint and the live value (Stockagent-main/secretary.py:36-221). The agent sends that reason back into the same conversation as a repair turn. After at most three repairs it falls back to a no-op default (Stockagent-main/agent.py:188-218).
2. **The simulation as a measuring instrument:**
   - fictional companies, so the model cannot draw on memorised knowledge of real tickers (Stockagent-main/README.md:6, Stockagent-main/prompt/agent_prompt.py:110-150);
   - stated next-day intentions logged next to realised actions (Stockagent-main/agent.py:405-425, Stockagent-main/record.py:63-141);
   - scripted, dated shocks that change both what agents are told and a parameter they actually pay (Stockagent-main/main.py:131-137).

The implementation is naive and buggy. The value for DRF is in these patterns and in the failure modes they warn against.

### 2. Architecture at a glance

```
init: 50 agents, random endowment + 1 of 4 risk labels + 1 legacy loan  Stockagent-main/util.py:161-163, Stockagent-main/agent.py:19-67
for date in 1..TOTAL_DATE(=10):                                          Stockagent-main/main.py:97
  wipe both books; clear every agent's chat_history; settle matured loans Stockagent-main/main.py:100-116
  monthly interest on REPAYMENT_DAYS; bankruptcy pass                     Stockagent-main/main.py:118-129
  dated shocks: overwrite util.LOAN_RATE + post message as author -1      Stockagent-main/main.py:131-137
  LLM#1 loan   -> Secretary.check_loan   -> AgentRecordDaily              Stockagent-main/main.py:139-143
  for session 1..3: shuffle order; LLM#2 order -> check_action -> book    Stockagent-main/main.py:145-164
                    price := last fill (else unchanged)                   Stockagent-main/main.py:166-169
  LLM#3 next-day intent -> check_estimate -> daily record                 Stockagent-main/main.py:172-180
  LLM#4 forum post -> injected into tomorrow's loan prompt                Stockagent-main/main.py:182-189
```

| Layer | Component | Role | Anchors |
|---|---|---|---|
| Orchestration | `simulation()` | Fixed phase order within each day | Stockagent-main/main.py:75-201 |
| Clearing | `handle_action` | Per-stock dict book, exact-price FIFO matching, partial fills | Stockagent-main/main.py:20-72 |
| Price | `Stock.update_price` | Last fill price, or the previous price carried forward | Stockagent-main/stock.py:21-26 |
| Cognition | `plan_loan` / `plan_stock` / `next_day_estimate` / `post_message` | Phase-specific prompts and a bounded repair loop | Stockagent-main/agent.py:142-319, Stockagent-main/agent.py:398-425 |
| Transport | `run_api*` | Routes on the substrings `gpt`/`gemini`, 2 attempts (`max_retry=2`), returns `""` on failure | Stockagent-main/agent.py:69-125 |
| Validation | `Secretary.check_loan/action/estimate` | Format, schema and state-feasibility checks | Stockagent-main/secretary.py:36-221 |
| Prompts | procoder `NamedBlock`/`NamedVariable` | Blocks assembled per phase and per day type | Stockagent-main/prompt/agent_prompt.py:4-197 |
| World constants | calendar, rates, reports, events, plus unused seeds, baselines and ideal-price bands | | Stockagent-main/util.py:34-38, Stockagent-main/util.py:124-281 |
| Logging | Four xlsx panels (trade tape, session prices, pre-trade state + order, daily loan + intents) and a text log | | Stockagent-main/record.py:1-141, Stockagent-main/log/custom_logger.py:19-41 |

### 3. Design philosophy (as the code shows it)

- **The world is deterministic; the LLM only decides.** Settlement, interest, bankruptcy and pricing are plain Python (Stockagent-main/agent.py:321-396, Stockagent-main/stock.py:21-26). The LLM never changes state directly.
- **The LLM is untrusted and the validator is trusted.** Every structured decision passes through a state-aware check, and the resulting reason is written for the model to read (Stockagent-main/secretary.py:158-176).
- **Time is a fixed calendar, and external factors are scripted.** Quarterly reports come on fixed days, rate shocks come on fixed days, and the phase order is fixed (Stockagent-main/util.py:243-281, Stockagent-main/main.py:97-189). This makes each channel separable in principle, which the paper's ablations depend on.
- **Memory is bounded to one day.** The whole day is one conversation. Chat history is wiped at dawn (Stockagent-main/main.py:114-116). Only explicit state, prices and the public forum carry over to the next day.
- **Leakage is controlled with fiction.** The companies are anonymous (A–D) with hand-typed synthetic fundamentals (Stockagent-main/prompt/agent_prompt.py:110-150).
- **Failures degrade to inaction and never crash**, with one exception: `loan_type: 1.0` passes validation and then raises an uncaught `TypeError` (Stockagent-main/secretary.py:81, Stockagent-main/agent.py:211). Transport failure, exhausted repairs and a genuine "no" all produce the same default (Stockagent-main/agent.py:192-207, Stockagent-main/agent.py:275-290). This is the design's main hidden cost.
- **Analysis happens offline.** The simulation computes no metrics at all, and even the end-of-run dumps are commented out (Stockagent-main/main.py:193-201).

### 4. Core mechanisms, ranked by importance to DRF

#### 4.1 Secretary: a validator that knows the agent's state (C10)

- **What it does.** It turns a raw LLM reply into one of three results: accepted, rejected with a specific reason, or parsed.
- **How it works.**
  1. Format gate: the reply must contain exactly one `{` and one `}`. The object is sliced out, all newlines and spaces are stripped, and the text goes to `json.loads` (Stockagent-main/secretary.py:38-54).
  2. The key field acts as a discriminator for a tagged union:
     - `loan:"no"` forbids `loan_type`/`amount`; `loan:"yes"` requires both, `loan_type ∈ {0,1,2}` and `0 < amount ≤ max_loan` (Stockagent-main/secretary.py:63-89).
     - For buy/sell, `stock ∈ {A,B}`, `price > 0` and integer `amount` are required (Stockagent-main/secretary.py:140-156).
  3. Feasibility against live state. A buy must satisfy `amount × limit_price ≤ cash`. The validator deliberately uses the agent's own limit price; a commented line shows the market price was considered and dropped (Stockagent-main/secretary.py:158-167). A sell must satisfy `amount ≤ holdings` (Stockagent-main/secretary.py:169-176).
  4. The failure messages include live values, for example "The cash you have now is {cash}…" (Stockagent-main/secretary.py:164-166) and "The amount of stock you hold is {hold_amount}" (Stockagent-main/secretary.py:173-175).
- **Why it matters for DRF.** The decision channel only filters. It has no validator that knows the actor's state:
  - A non-candidate scenario is dropped silently (backend/app/services/decision_channel.py:276-277).
  - `agent_id` is never checked against the roster, and `magnitude`/`confidence` are passed through unchanged (backend/app/services/decision_channel.py:278-283).
  - An id that is not in the roster gets default power 1.0 (backend/app/services/decision_channel.py:333-334, backend/app/services/worldstate.py:111-113).
  - The prompt asks for `magnitude` in 0-1 (backend/app/services/decision_channel.py:207), but WorldState only floors it at 0 (backend/app/services/worldstate.py:105, backend/app/services/worldstate.py:211-212). A single reply with magnitude 5 outweighs five compliant commitments. This is the same prompt-versus-validator drift StockAgent suffers from (see §5).
  - A round counts as `committed` if even one decision is valid, however many roster members failed (backend/app/services/decision_channel.py:284-285).

#### 4.2 Repair turn with targeted feedback in the same conversation, bounded, then a typed default (C10, C26)

- **How it works.** `run_api` appends every prompt and reply to `self.chat_history` (Stockagent-main/agent.py:81-88, Stockagent-main/agent.py:101-117). A retry is therefore a follow-up turn: the model sees its bad answer, the validator's reason and the schema again. The retry prompts are Stockagent-main/prompt/agent_prompt.py:57-68, Stockagent-main/prompt/agent_prompt.py:96-107 and Stockagent-main/prompt/agent_prompt.py:188-197. There are at most 1+3 calls per decision (Stockagent-main/agent.py:188-209, Stockagent-main/agent.py:271-292, Stockagent-main/agent.py:412-424).
- **Why it matters for DRF.** `chat_json` makes one blind resend: the same messages at a temperature 0.2 lower, with no information about what was wrong (backend/app/utils/llm_client.py:584-599). A generic `chat_json_validated(messages, validator, max_repairs)` would fix this. It should append the bad reply plus a user turn such as "agents 3,7 used scenario X; candidates are […]; id 12 is not on the roster". This would recover commitments that are thrown away today.
- **Keep DRF's current typed statuses.** DRF already separates `failed`, `silent` and `abstained` (backend/app/services/decision_channel.py:230-265, backend/app/services/worldstate.py:43-67). When repairs run out, the result must be `failed`, not a fake no-op.
- **Charge repair calls to the budget ledger.**
- **Lesson.** StockAgent copied this loop three times, and one copy broke (§5, loan retry).

#### 4.3 Fallback treated as inaction: the negative lesson (C26)

- **How it goes wrong.**
  - Any model name that contains neither `gpt` nor `gemini` makes `run_api` return `None` (Stockagent-main/agent.py:69-73). That includes util's own `Claude-4.6-Sonnet`, `DeepSeek-V4-flash`, and its capitalised `DEFAULT_MODEL` `Gemini-3.5-flash` (Stockagent-main/util.py:25-40). The routing check is case-sensitive.
  - Validation then fails four times and every decision becomes a logged "no". The xlsx records a fallback "no" exactly like a real one (Stockagent-main/record.py:114-118). A dead market looks like a quiet market.
- **Why it matters for DRF.**
  - OASIS swallows per-agent model errors (backend/scripts/run_parallel_simulation.py:2024-2027). DRF counts calls and errors **per platform** and marks the platform `degraded` only when the error rate exceeds 0.5 (backend/scripts/run_parallel_simulation.py:2270-2298).
  - `hollow` fires only when `organic_count == 0` (backend/app/services/simulation_runner.py:2125-2132).
  - So a run where 40% of calls failed, or where one pivotal actor failed in every round, still reports `ok`.
- **What to transplant.** Tag each fallback or defaulted decision (`is_fallback`). Record per-actor error and fallback shares. Demote the run when a pivotal actor (high `outcome_power`) is mostly fallback, even if the platform-wide rate is under threshold.

#### 4.4 Stated intent logged beside realised action: a say-do probe (C16)

- **How it works.**
  1. After the last session, each agent answers yes/no for buy/sell per stock and for a loan tomorrow. This happens inside the same day's conversation, so the answer is conditioned on the day's trades (Stockagent-main/prompt/agent_prompt.py:175-185, Stockagent-main/agent.py:405-425).
  2. The answer is validated (Stockagent-main/secretary.py:183-221) and stored next to today's loan (Stockagent-main/record.py:63-100, Stockagent-main/main.py:172-180).
  3. Tomorrow's realised orders go to the session panel (Stockagent-main/record.py:102-141). The comparison between the two is left to offline analysis.
  4. **Key property:** tomorrow's chat is wiped before the next decision (Stockagent-main/main.py:114-116). The agent never sees its own promise, so consistency is a real behavioural probe rather than self-imitation. The only leak path is the agent's own forum post.
- **Why it matters for DRF.** DRF has no intent elicitation; a grep of decision_channel.py, agent_dynamics.py, worldstate.py and run_parallel_simulation.py finds none.
  - **Cheapest form:** add an optional `next_period_intent` (scenario plus action type) to the existing batched round JSON (backend/app/services/decision_channel.py:209-211), and score it against the next period's commitment.
  - **Keep the intent out of the next round's prompt.** Elicitation is by design a pure function of the frozen log, which is what makes the rounds parallel-safe (backend/app/services/decision_channel.py:16-20). Feeding the intent back would break both the probe and that property.
  - **Uses:**
    - per-actor say-do rate as a persona-fidelity and drift metric;
    - near-zero consistency as a hollowness or noise signal for the health gate;
    - aggregated intents as a leading indicator.
  - **Diagnostics only.** Under the default `SIMULATION_FORECAST_EFFECT=diagnostic_only`, sim outputs must not enter spine probability inputs (backend/app/config.py:1475-1488, backend/app/services/report_agent.py:2860-2878). Intents stay diagnostic.

#### 4.5 Dated shocks that couple a narrative with a structural change, from a privileged author (C31, C42)

- **How it works.**
  - On `EVENT_n_DAY` the code overwrites the global `util.LOAN_RATE` and appends `{"name": -1, "message": …}` to the forum list (Stockagent-main/main.py:131-137). Id -1 is reserved for admin (Stockagent-main/main.py:83).
  - The new rates appear in the loan menu (Stockagent-main/agent.py:159-161, Stockagent-main/agent.py:182-184).
  - Repayment and interest read the current rate at the time of payment, so the shock also reprices loans already outstanding (Stockagent-main/agent.py:359, Stockagent-main/agent.py:370).
  - Agents therefore both **hear** the news and **pay** for it.
- **Why it matters for DRF.**
  - DRF's scheduled events are text only. The event record is `{round, content, date, poster_agent_id, poster_name}` (backend/app/services/simulation_config_generator.py:1040-1041). It is fired as a `CREATE_POST` by a real actor (backend/scripts/run_parallel_simulation.py:2543-2553), and when the text names no actor, that actor is **the highest-influence agent** (backend/app/services/simulation_config_generator.py:1039). Exogenous news can therefore reach the feed in an unrelated actor's voice. StockAgent's reserved author id avoids this. DRF's `CONFIRMED EVENTS` header block is already a clean privileged channel (backend/scripts/run_parallel_simulation.py:1974-2006).
  - **Transplant 1:** give each event an optional typed `structural_delta`, for example an actor's `outcome_power` ×k or a shift in the WorldState prior. Apply it deterministically when the event fires, log it, and make it switchable per event for counterfactual arms.
  - **Transplant 2:** route actor-less events through a system identity or the header only, not through a borrowed actor.
  - **Avoid StockAgent's global module mutation.** Apply deltas to a per-run state object.

#### 4.6 A capability limit stated in the prompt and enforced by the validator (C31)

- **How it works.**
  - `max_loan = init_proper − Σ outstanding loans` (Stockagent-main/agent.py:136-140, Stockagent-main/agent.py:150, Stockagent-main/agent.py:170).
  - The prompt states it: "The loan amount shall not exceed {max_loan}" (Stockagent-main/prompt/agent_prompt.py:46).
  - The validator enforces the same number and quotes it back (Stockagent-main/secretary.py:85-88).
  - When the limit makes the decision moot (`max_loan ≤ 0`), no LLM call is made at all (Stockagent-main/agent.py:186-187).
- **Why it matters for DRF.** DRF has a consumer for actor capability but no producer.
  - `outcome_power` is read only from explicit declarations (backend/app/services/decision_channel.py:360-380). Outside decision_channel.py, the only other caller of that reader is backend/scripts/run_parallel_simulation.py:3406.
  - Every actor therefore gets the declared-neutral 1.0 with `outcome_power_known=False` (backend/app/services/decision_channel.py:417-422).
  - The StockAgent chain (state → prompt → validator → mutation by shocks, §4.5) is the template. Derive per-actor capability from the dossier in PREPARE, render it in the round prompt, reject commitments that exceed it, and let events change it.

#### 4.7 Fictional entities for leakage control (C21)

- **How it works.**
  - The companies are anonymous A–D with synthetic 12-quarter histories (Stockagent-main/prompt/agent_prompt.py:110-132).
  - The rewrite replaced leading narrative with "Please infer and update your beliefs…" (Stockagent-main/prompt/agent_prompt.py:146).
  - FCFF "ideal price" bands and a clamped piecewise-linear midpoint interpolator exist, but the interpolator has no callers and the bands are used only for their day-1 midpoint, which sets each stock's initial price (Stockagent-main/util.py:85-111, Stockagent-main/util.py:168-191).
- **Why it matters for DRF.**
  - golden_eval scores resolved 2024-2026 questions. Its only guard against hindsight is a written instruction to run with an AS-OF constraint (backend/scripts/golden_eval.py:7-9, backend/scripts/golden_eval.py:19-22), which cannot stop the model's own parametric memory.
  - DRF has no pseudonymisation code: a grep for pseudonym, anonymi, mask_entity and similar found nothing. In DRF, "leakage" means simulation-mechanics wording leaking into prose (backend/app/services/report_lint.py:152-160).
  - **Transplant (C21):** a masked replay. Replace actor and entity names and absolute dates in the dossier with a consistent pseudonym and date-offset map. Re-derive the spine, which is cheap and needs no simulation. Compare probabilities and Brier with the named run. A large gap means backtest skill is inflated by memorised outcomes.
  - The paper's own caveat applies: events modelled on 2014-2019 conditions stay recognisable. The measured gap is therefore a lower bound on leakage.

#### 4.8 One channel at a time ablation, non-LLM baselines, seed expansion (C30)

- **How it works.**
  - The information channels are separable blocks:
    - events and loans (Stockagent-main/main.py:131-143);
    - the forum (Stockagent-main/main.py:182-189);
    - disclosures (Stockagent-main/agent.py:225-268).
  - The paper removes one channel per arm, but the code has no switches, so ablation meant editing code.
  - `NON_LLM_BASELINES` (Fundamental, Trend, Noise) and `expand_experiment_seeds` exist only as configuration: nothing calls `is_non_llm_baseline`, and the seed helper runs only at import to fill seed constants that nothing reads (Stockagent-main/util.py:34-38, Stockagent-main/util.py:80-82, Stockagent-main/util.py:124-158). The seed helper cycles through the base seeds and adds 10007×⌊i/len⌋, so seeds stay unique past the base list.
  - `random.seed` is never called anywhere (grep).
- **Why it matters for DRF.**
  - Promoting simulation output to `validated_update` needs outcome-blind forward evidence (backend/app/config.py:1479-1480, backend/app/services/decision_channel.py:730-732). Control arms produce exactly that evidence:
    - **(a) Heuristic-actor arm.** Each actor commits to its seeded-prior or incentive argmax, with no LLM. If the LLM channel's WorldState does not diverge from this arm, the simulation added no information.
    - **(b) Leave-one-channel-out at the spine layer.** Drop the market block, the quantitative facts, or one key event, and record Δp for each binary forecast. Flag forecasts that hinge on a single source.
  - Full OASIS reruns are expensive, so start at the spine layer. Use the event switches from §4.5 as the simulation-level arm.

#### 4.9 The backbone is the largest variable (a paper finding, not in the candidate list)

- **Paper finding.** On identical inputs, GPT agents went long and Gemini agents went short. A-share volume differed by about 24× (3,118,792 vs 128,981 shares). The backbone also controlled herding.
- **Why it matters for DRF.** DRF has an uncontrolled confound. Twitter builds its model with `use_boost=False` (backend/scripts/run_parallel_simulation.py:4692, backend/scripts/run_parallel_simulation.py:4732) and Reddit with `use_boost=True` (backend/scripts/run_parallel_simulation.py:5228, backend/scripts/run_parallel_simulation.py:5268). The boost model is used whenever `LLM_BOOST_API_KEY` is set on the OpenAI-compatible path (backend/app/utils/oasis_llm.py:495-504, backend/app/utils/oasis_llm.py:584). Differences between Twitter and Reddit can then be a backbone artifact.
  - Seed ensembles vary only the simulation run, and `pool_binary_forecasts` pools extraction models over the same research dossier (backend/app/services/ensemble.py:1-9, backend/app/services/ensemble.py:261-275). The simulation backbone is never varied.
  - **Action:** record the backbone per platform in the run manifest and the provenance of each forecast signal, and warn when the platforms differ.

#### 4.10 Random turn order each session (C26)

- **How it works.** The code shuffles the agent order each session and has agents act serially on a live book, so later movers see earlier orders (Stockagent-main/main.py:147-164). The order is not seeded and not logged.
- **Why it matters for DRF.** The decision-channel roster is sorted by activation in descending order (backend/app/services/decision_channel.py:424) and rendered in that fixed order into a batched prompt (backend/app/services/decision_channel.py:182, backend/app/services/decision_channel.py:212). That creates a position bias. The cache key is already a sorted signature (backend/app/services/decision_channel.py:442-450), so a seeded shuffle of the rendered order, keyed on the run seed and round, costs nothing and stays deterministic.

#### 4.11 Typed phases per day, and the coupling of persona to a skippable phase (C42)

- **How it works.**
  - Each phase has its own prompt, schema, validator and default (Stockagent-main/agent.py:142-319, Stockagent-main/agent.py:398-425).
  - The role frame ("You are a stock trader"), the risk label, the forum and the government events appear **only** in the loan prompt (Stockagent-main/agent.py:146-185, Stockagent-main/prompt/agent_prompt.py:40).
  - When `max_loan ≤ 0`, that phase returns before any call is made (Stockagent-main/agent.py:186-187). A fully leveraged agent then trades all day with no persona, no forum and no news, because the trading prompts omit them (Stockagent-main/agent.py:227-228, Stockagent-main/agent.py:243-244).
- **Why it matters for DRF.** DRF's world-clock header, which carries events and the world delta, is injected per agent on a best-effort basis:
  - a failure for one agent is skipped silently (backend/scripts/run_parallel_simulation.py:2012-2020);
  - the whole injection returns early if the camel import fails (backend/scripts/run_parallel_simulation.py:1957-1961).
  - **Transplant:** count successful header injections against active agents each round and record the count as a round health field. Add a test that renders every phase prompt on its own and asserts that the role contract, the world-delta block and the event block are present.

#### 4.12 Episodic daily memory, with the public post as the only diary (C42, stance continuity)

- **How it works.** One conversation per day: the first call carries the full context and later calls carry only deltas (Stockagent-main/agent.py:222-268). At dawn the history is wiped (Stockagent-main/main.py:115), so an agent's own forum post is the only way its reasoning survives into the next day (Stockagent-main/main.py:182-189).
- **What DRF could take.** An explicit, labelled "your previous position" slot in the round prompt: a cheap way to keep an actor's stance continuous across calendar periods. DRF agents already keep their memory across rounds, and the header is written with USER role precisely so it is not dropped (backend/scripts/run_parallel_simulation.py:1943-1953). This slot is therefore low priority.

#### 4.13 Small tricks worth keeping

- **Post-condition assertion on a state transition.** After forced liquidation, any negative holding or cash raises `RuntimeError("ERROR: WRONG BANKRUPT PROCESS")` (Stockagent-main/agent.py:393-394).
- **Skip the LLM when the decision is moot** (Stockagent-main/agent.py:186-187). In DRF, log such a skip as `missing`, not as a "no". StockAgent records it as a no-loan (Stockagent-main/main.py:142-143).
- **Snapshot the state before each decision on the decision row.** Total assets, cash and per-stock values are recorded before matching (Stockagent-main/main.py:156-157, Stockagent-main/record.py:102-141). This lets outcomes be attributed afterwards.
- **Remove leading narrative.** The original prompt, preserved in bytecode, told agents the price "is expected to continue rising". The current source is neutral (Stockagent-main/prompt/agent_prompt.py:135-150). DRF already tells agents the opposite of an activity nudge: "Doing nothing is a legitimate strategic choice" (backend/scripts/run_parallel_simulation.py:1995). Keep it, and add a test that forbids activity-encouraging or stance-seeding wording.

### 5. Commodity, weak or buggy: do not copy

| Item | Defect | Anchors |
|---|---|---|
| Settlement | `buy_stock/sell_stock(stock, close_amount, price)` is called against the signature `(stock_name, price, amount)`. Cash comes out right because the product commutes, but share counts move by the price. The `False` returns are ignored, so one leg can fail while the other settles and the price still moves. | Stockagent-main/main.py:28-30, Stockagent-main/main.py:53-54, Stockagent-main/agent.py:321-351 |
| Matching | Trades only on exact float equality, with no crossing rule and no tick size. No escrow: each resting buy can be sized to the agent's full cash. An equal-size fill leaves a 0-share resting order, which later produces a 0-quantity trade record. The broad `except` leaves the book half-updated. | Stockagent-main/main.py:24-25, Stockagent-main/main.py:40-44, Stockagent-main/main.py:64-68, Stockagent-main/main.py:70-72 |
| Price history | `history[date] = session_deal` and then `session_deal.clear()` on the same list, so the history is always empty. Stale carry-forward prices are logged exactly like real ones. | Stockagent-main/stock.py:21-26 |
| Loan retry | `check_loan(date, resp)` against the signature `check_loan(resp, max_loan)`, so every repair fails and only first-shot loan answers can succeed | Stockagent-main/agent.py:208, Stockagent-main/secretary.py:36 |
| Validator | Brace counting rejects nested JSON. Stripping all spaces corrupts string values. The broad `except` returns an **empty** reason, so the repair prompt carries no guidance. Enums are compared lowercased, but the raw dict is returned and consumers compare case-sensitively, so `"Buy"` or `"Yes"` silently become no-ops. `1.0 ∈ [0,1,2]` passes, then list indexing crashes. | Stockagent-main/secretary.py:38-47, Stockagent-main/secretary.py:63, Stockagent-main/secretary.py:81, Stockagent-main/secretary.py:91-95, Stockagent-main/secretary.py:179-181, Stockagent-main/agent.py:210-211, Stockagent-main/agent.py:294-319 |
| Prompt examples | `loan_type: 3` and the unquoted keys `amount: 100, price : 30.1` both fail the prompt's own validator | Stockagent-main/prompt/agent_prompt.py:48-49, Stockagent-main/prompt/agent_prompt.py:89, Stockagent-main/prompt/agent_prompt.py:102 |
| Drift between prompt and code | The prompts offer stocks A–D and C/D placeholders that agent.py never supplies. The validator allows only A/B. Loan terms are "1/2/3 years" in the prompt but 22/44/66 days in code. Rendering behaviour is unverified because procoder is not vendored. | Stockagent-main/prompt/agent_prompt.py:19, Stockagent-main/prompt/agent_prompt.py:26-34, Stockagent-main/prompt/agent_prompt.py:76-82, Stockagent-main/agent.py:229-268, Stockagent-main/secretary.py:145-148, Stockagent-main/util.py:238-239 |
| Horizon vs calendar | `TOTAL_DATE=10`, but reports start on day 12, interest on day 22 and events on days 78 and 144. Under the defaults, no scheduled mechanism ever fires. DRF already moves events past the horizon into `beyond_horizon_events` (backend/app/services/simulation_config_generator.py:1069-1090). | Stockagent-main/util.py:162, Stockagent-main/util.py:241, Stockagent-main/util.py:245, Stockagent-main/util.py:272-281 |
| Credit model | Principal is repaid at the full-period rate on top of the monthly `/12` coupons, so interest is charged twice. The solvency check ignores debt. Liquidation sells to the house, off the book. | Stockagent-main/agent.py:353-372, Stockagent-main/agent.py:374-391 |
| Records | `AgentRecordDaily(date, agent.order, loan)` against `__init__(agent, date, …)` swaps the trader and day columns. Every row costs a full xlsx read and rewrite, which is O(n²) and not atomic. `res/` is never created. | Stockagent-main/main.py:143, Stockagent-main/record.py:15-27, Stockagent-main/record.py:63-100 |
| Forum | Every post goes into every prompt, with no cap and no ranking. It is not anonymous: author ids are included. Empty or `None` posts from failures are included. DRF's capped, influence-ranked `world_delta` is stronger (backend/app/services/world_delta.py:1-33). | Stockagent-main/main.py:182-189, Stockagent-main/prompt/agent_prompt.py:14-23 |
| Activity nudge | "We encourage you to buy and sell more" biases the very volume and frequency metrics the paper compares | Stockagent-main/prompt/agent_prompt.py:87 |
| Persona | A one-word label drawn at random from four, reaching the model only through the loan prompt | Stockagent-main/agent.py:57, Stockagent-main/prompt/agent_prompt.py:40 |
| Transport | Routing by substring, a new client per call, no timeout or backoff, no cost accounting, and failed user turns left in history | Stockagent-main/agent.py:69-125 |
| Unused scaffolding | Seeds, baselines, the ideal-price interpolator, company constants and the model alias table are never used (the ideal bands only set each stock's day-1 price). The Secretary's LLM path has a hard-coded empty key and is never called. | Stockagent-main/util.py:25-158, Stockagent-main/util.py:193-231, Stockagent-main/secretary.py:7-26 |
| Dependencies | requirements.txt omits google-generativeai, procoder and openpyxl | Stockagent-main/requirements.txt:1-6, Stockagent-main/agent.py:7, Stockagent-main/README.md:25-28 |

### 6. Lessons from the repo's history

There is no `.git` directory and there are no tests. The repo's evolution shows up in stale bytecode and in commented-out code.

- **The rewrite introduced the drift.** The compiled prompt (`prompt/__pycache__/agent_prompt.cpython-39.pyc`) is the original two-stock version with "22days/44days/66days" loan terms. The source rewrite moved to four stocks and changed the terms to years (Stockagent-main/prompt/agent_prompt.py:26-34). main, agent, stock and secretary were never migrated (Stockagent-main/main.py:78-80, Stockagent-main/secretary.py:145-148). The `loan_type: 3` example is in both versions, so the examples were never tested against the validator.
- **Leading narrative was removed on purpose.** The bytecode carries a new-CEO story, "expected to continue rising", data concealment before the IPO, and subsidies. The source replaced these with neutral framing (Stockagent-main/prompt/agent_prompt.py:135-150). This is an implicit admission that injected narrative steers the agents.
- **Stale bytecode leaks secrets.** `__pycache__/util.cpython-39.pyc` contains a hard-coded Google key literal next to the string "DONT FORGET TO DELETE!!!". The value is deliberately not reproduced here. The source now reads settings or the environment and treats `REPLACE_WITH_*` placeholders as unset (Stockagent-main/util.py:9-17).
- **An off-by-one was fixed.** `randint(0, len(LOAN_TYPE))` became `len-1` (Stockagent-main/agent.py:31 vs the commented original at Stockagent-main/agent.py:46).
- **Token overflow was handled by resetting, not truncating.** The tiktoken-based truncation is commented out (Stockagent-main/agent.py:105-106). Instead, chat history is cleared daily (Stockagent-main/main.py:115).
- **Abandoned features leave traces.** The IPO issuer with a decaying offer is commented out (Stockagent-main/main.py:79, Stockagent-main/main.py:94, Stockagent-main/main.py:105-111), yet the prompt still calls B "newly listed" (Stockagent-main/prompt/agent_prompt.py:8). `action_history` is allocated but never written, and it would go out of range on the last day if re-enabled, because `date` is 1-based (Stockagent-main/agent.py:63).
- **Copying loops copies bugs.** The loan retry arguments are swapped in one of three copied loops (Stockagent-main/agent.py:208). The trade loop logs "Skip as no loan today" (Stockagent-main/agent.py:284).

**Meta-lesson for DRF.** DRF shows the same class of drift. The docstring says the decision channel is "default OFF" (backend/app/services/decision_channel.py:12-13), while config defaults it to `true` and its own comments contradict each other (backend/app/config.py:1470-1474).

### 7. Paper claims vs code reality

| Paper claim | Code reality |
|---|---|
| A per-share fee of 0.005 (minimum 1, maximum 5.95) | Absent: there is no fee logic in any .py file (grep). Settlement is `price × amount` only (Stockagent-main/agent.py:327, Stockagent-main/agent.py:350). |
| A trade executes when bid and ask match | Exact float equality only, with no crossing (Stockagent-main/main.py:25, Stockagent-main/main.py:50) |
| A "random clock page replacement" scheme avoids contention | A plain unseeded `random.shuffle` (Stockagent-main/main.py:147-149) |
| The secretary corrects invalid responses, following WarAgent | Pure-Python checks; the LLM path is dead code (Stockagent-main/secretary.py:7-26) |
| A bankrupt agent liquidates and exits | Exits only if net worth is below 0. Otherwise it partially liquidates to the house and continues (Stockagent-main/agent.py:374-396). |
| Forum posts are anonymous | Author ids are attached (Stockagent-main/main.py:189) |
| Interest is paid before loan repayment (fig/workflow2.png) | Repayment runs first, then interest (Stockagent-main/main.py:113-121) |
| Loan terms of 1/2/3 months | The prompt says years; the code uses 22/44/66 trading days (Stockagent-main/prompt/agent_prompt.py:30-32, Stockagent-main/util.py:239) |
| Four personalities drive behaviour | The label appears only in the loan prompt (Stockagent-main/prompt/agent_prompt.py:40) |
| 200 agents | The default is 50 (Stockagent-main/util.py:161) |
| Leakage is avoided | Real US stocks are anonymised, but events are modelled on 2014-2019 conditions (paper). Name masking does not stop pattern recall. |
| RQ3 ablation of rate changes over 10 days (text) | Under this calendar, the rate events (days 78 and 144) cannot fire in 10 days. Only the 154-day version in Table 9 could exercise that channel (Stockagent-main/util.py:272-281). |
| RQ3 ablations, and multiple runs implied by util | No switches for channels. util defines three runs per research question but never seeds the RNG (Stockagent-main/util.py:148-158). |
| Evaluation against an FCFF ideal-price band | The bands only set the initial price (the day-1 midpoint); nothing evaluates against them, and `Stock.ideal_price` stays 0 (Stockagent-main/util.py:168-191, Stockagent-main/stock.py:7) |
| GPT vs Gemini results | Not reproducible from the repo: no seeds, a single run per arm, no significance tests. The backbone effect is still the paper's most robust finding (§4.9). |

### 8. What DRF should take, and what not

| Candidate | Take? | What exactly | Where in DRF |
|---|---|---|---|
| **C10** Validated structured outputs | **Yes, high priority** | 1. `validate(obj, live_state) -> (ok, reasons, normalized)`.<br>2. Reasons name the violated constraint and the live value.<br>3. Always return the normalized object; StockAgent's case gap shows why.<br>4. One or two repair turns appended to the conversation.<br>5. On exhaustion, a typed `failed` status.<br>6. A unit test that runs every prompt example through its validator. | backend/app/utils/llm_client.py:569-599 (new helper beside it)<br>backend/app/services/decision_channel.py:262-286: roster-id check, duplicate ids, clamp magnitude and confidence to [0,1] to match the prompt at backend/app/services/decision_channel.py:207 |
| **C26** Integrity of decision elicitation | **Yes** | 1. An `is_fallback` tag on each decision, and per-actor error and fallback shares.<br>2. Roster coverage per round (valid decisions ÷ roster), not just "≥1 valid".<br>3. Abstention must come with a one-line reason; the validator rejects a bare abstain.<br>4. A seeded shuffle of the rendered roster order. | backend/app/services/decision_channel.py:199-201, backend/app/services/decision_channel.py:273-285, backend/app/services/decision_channel.py:424<br>backend/scripts/run_parallel_simulation.py:2270-2298 |
| **C16** Stated intent and say-do scoring | **Yes** | 1. Optional `next_period_intent` in the batched round JSON.<br>2. Never fed back into the prompt.<br>3. Scored deterministically against the next period's commitment.<br>4. Diagnostic and health-gate use only. | backend/app/services/decision_channel.py:209-211, backend/app/services/decision_channel.py:16-20<br>backend/app/config.py:1475-1488 |
| **C31** Actor capability state | **Yes** | 1. A PREPARE-stage producer of `outcome_power` and capacity from the dossier.<br>2. The capability rendered in the prompt and enforced by the C10 validator.<br>3. Mutable through event `structural_delta`s. | backend/app/services/decision_channel.py:360-380, backend/app/services/decision_channel.py:417-422 |
| **C42** Completeness of the round prompt | **Yes** | 1. Count header injections per active agent.<br>2. A system author for events that name no actor.<br>3. A "your previous position" slot.<br>4. Render tests for each phase in isolation. | backend/scripts/run_parallel_simulation.py:1957-2020, backend/scripts/run_parallel_simulation.py:2543-2553<br>backend/app/services/simulation_config_generator.py:1039 |
| **C30** Counterfactual arms | **Yes, staged** | 1. A heuristic-actor control arm.<br>2. Leave-one-channel-out at the spine layer first.<br>3. Event toggles as the simulation-level arm.<br>4. Seed expansion (base list plus a prime offset) for ensembles.<br>This is the evidence base for promotion to `validated_update`. | backend/app/config.py:1479-1480<br>backend/app/services/ensemble.py:1-9 |
| **C21** Masked replay | **Yes, for evaluation** | Consistent pseudonym and date-offset map, spine re-derived only, named-vs-masked gap reported as a lower bound on leakage | backend/scripts/golden_eval.py:19-22<br>backend/app/services/backtest.py:1-11 |
| Backbone confound (not in the candidate list) | **Yes, cheap** | 1. Record the backbone per platform in the manifest and in forecast-signal provenance.<br>2. Warn when Twitter and Reddit backbones differ.<br>3. An optional cross-backbone arm, with the spread reported as epistemic uncertainty. | backend/scripts/run_parallel_simulation.py:4732, backend/scripts/run_parallel_simulation.py:5268<br>backend/app/utils/oasis_llm.py:495-504 |
| **C48** An intra-simulation belief market | **Not now** | StockAgent's clearing is the counter-example: exact-match matching, no escrow, legs that settle half-way (§5). Under `diagnostic_only`, a probability implied by the simulation cannot move forecasts anyway. If one is ever built, use an LMSR market maker with conservation asserts, not a continuous double auction. | backend/app/config.py:1475-1488, backend/app/services/decision_channel.py:725-745 |

**Do not take:**
- the order book and settlement code;
- last-trade pricing with silent stale carry-forward;
- global mutation of module state for shocks;
- unbounded injection of the whole forum;
- the unconditional activity nudge;
- random single-label personas (DRF's dossier-grounded ACTOR-CAST is far richer);
- merging transport failure, exhausted repairs and genuine abstention into one default;
- brace-count JSON extraction;
- copy-pasted retry loops;
- xlsx append logging;
- the transport layer (DRF's `llm_client` is far ahead).

Take the patterns (a validator that knows state, the say-do probe, shocks that change state, fiction-style leakage control, single-channel ablation) and reimplement them. No code may be copied, because the repo has no license.

## TradingAgents

TradingAgents-0.5.1 is by Tauric Research and is Apache-2.0 licensed. Its CHANGELOG covers 0.1.0 (2025-06-05) to 0.5.1 (2026-09-24): `TradingAgents-0.5.1/CHANGELOG.md:595`, `TradingAgents-0.5.1/CHANGELOG.md:9`.

### 1. Essence

TradingAgents is a LangGraph pipeline that turns one (ticker, trade_date) into a 5-tier rating (Buy / Overweight / Hold / Underweight / Sell). It is modelled on a trading desk:

- up to four analysts write reports into shared state;
- a Bull/Bear debate follows, judged by a Research Manager;
- a Trader then writes a plan, three risk debaters argue over it, and a Portfolio Manager makes the final call.

The wiring is in `TradingAgents-0.5.1/tradingagents/graph/setup.py:78-125`. The paper sells the role-play, but it never ablates it. The code is worth mining for something else: about fifteen months of hardening, each fix tied to an issue number, built around two ideas.

**(a) State exactly what was known, and as of when. Never let absence or ambiguity pass as a fact.**
- An unreadable decision becomes the `REVIEW` sentinel, never Hold (`TradingAgents-0.5.1/tradingagents/agents/rating.py:27-31`).
- An empty prompt slot is named as absent (`TradingAgents-0.5.1/tradingagents/agents/context.py:33-44`, `TradingAgents-0.5.1/tradingagents/agents/context.py:180-208`).
- A window a feed never observed is reported as "unavailable … not an absence" (`TradingAgents-0.5.1/tradingagents/dataflows/date_window.py:38-62`).
- The run date is injected by the server, hidden from the model, and clamped (`TradingAgents-0.5.1/tradingagents/agents/tools.py:1-35`, `TradingAgents-0.5.1/tradingagents/dataflows/date_window.py:72-95`).
- Data that only exists live is withheld from past-dated runs (`TradingAgents-0.5.1/tradingagents/dataflows/date_window.py:98-124`).

**(b) A closed learning loop that is safe with respect to time.**
- Each decision is logged as pending.
- It is settled only after its full outcome window has traded, and then reflected on with a prompt that names the window.
- It is stamped with the date its outcome became knowable.
- A later run sees it only if that run's as-of date is on or after the stamp.
- Code: `TradingAgents-0.5.1/tradingagents/graph/settlement.py:38-132`, `TradingAgents-0.5.1/tradingagents/decision_log.py:73-110`, `TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:130-139`.

Almost every fix comes with a regression test that asserts on the rendered prompt or on the persisted artifact.

### 2. Architecture at a glance

```
CLI / propagate() ──► create_run_state: settle_pending → get_past_context(as_of) → identity → portfolio
                       (TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:260-299)
START → [Analyst_k ⇄ tools_k] → MsgClear_k → … → Bull ⇄ Bear ─count≥2R─► Research Manager(deep)
                                                                              │
   Portfolio Manager(deep) ◄─count≥3R─ Aggressive→Conservative→Neutral ◄─ Trader
        │
   final_trade_decision → parse_rating → signal │ decision log (pending) │ backtest scoring
```

| Layer | Components | Anchors |
|---|---|---|
| Run entry | Validates a canonical, non-future run date. A single state constructor is shared by the CLI and the API. | `TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:29-40`, `TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:260-299` |
| Agent graph | Analysts run sequentially, each with a message reset and, when it has tools, a tool loop (the sentiment analyst has none). Routers terminate on counters. Every edge gets the complete path map. | `TradingAgents-0.5.1/tradingagents/graph/setup.py:26-47`, `TradingAgents-0.5.1/tradingagents/graph/setup.py:97-125`, `TradingAgents-0.5.1/tradingagents/graph/conditional_logic.py:12-33`, `TradingAgents-0.5.1/tradingagents/graph/analyst_execution.py:7-72` |
| Decision contract | Pydantic schemas are rendered to canonical markdown, with one free-text retry and one shared rating parser. | `TradingAgents-0.5.1/tradingagents/agents/structured.py:31-89`, `TradingAgents-0.5.1/tradingagents/agents/schemas.py:95-138`, `TradingAgents-0.5.1/tradingagents/agents/rating.py:22-93` |
| Memory and evaluation | A markdown decision log holds each entry as pending, then resolved. Settlement is measured against a regional benchmark, a reflection is written, and a grid backtest reuses the same path. | `TradingAgents-0.5.1/tradingagents/decision_log.py:9-335`, `TradingAgents-0.5.1/tradingagents/graph/settlement.py:13-132`, `TradingAgents-0.5.1/tradingagents/graph/reflection.py:11-61`, `TradingAgents-0.5.1/tradingagents/backtest.py:1-208` |
| Data layer | Tools declared with `@tool` receive `InjectedState('trade_date')`, apply the `as_of` clamp, then call `route_to_vendor`. The router uses an explicit chain, typed errors and sentinels. Vendors: yfinance, SEC EDGAR, FRED/ALFRED, Polymarket, Reddit, StockTwits, Alpha Vantage. | `TradingAgents-0.5.1/tradingagents/agents/tools.py:1-35`, `TradingAgents-0.5.1/tradingagents/dataflows/router.py:184-291`, `TradingAgents-0.5.1/tradingagents/dataflows/errors.py:1-55` |
| LLM transport | Factory, a `ProviderSpec` registry, a `ModelCapabilities` table, reasoning knobs gated by model version, and `normalize_content`. | `TradingAgents-0.5.1/tradingagents/llm_clients/openai_client.py:183-334`, `TradingAgents-0.5.1/tradingagents/llm_clients/capabilities.py:93-135`, `TradingAgents-0.5.1/tradingagents/llm_clients/base_client.py:6-22` |
| Config and resume | A typed env overlay, a `run_config` scoped by a ContextVar, and a checkpoint thread-id that includes a run-shape signature. | `TradingAgents-0.5.1/tradingagents/default_config.py:36-75`, `TradingAgents-0.5.1/tradingagents/dataflows/config.py:1-64`, `TradingAgents-0.5.1/tradingagents/graph/checkpointer.py:19-45` |

Who sees what. Evidence and verdict are kept apart, and each role only sees part of the state:

| Role (tier) | Sees | Does not see |
|---|---|---|
| Analysts (quick) | Tools, instrument context and date. Told: "Report what your tools support; another agent decides the trade" (`TradingAgents-0.5.1/tradingagents/agents/analysts/market_analyst.py:62`). | Other analysts' tool traffic, which is wiped at the reset (`TradingAgents-0.5.1/tradingagents/agents/context.py:211-235`). |
| Bull/Bear (quick) | The 4 reports (marked when absent), the debate history, the opponent's last turn. | The portfolio. A test enforces this (`TradingAgents-0.5.1/tests/test_portfolio_context.py:153-159`). |
| Research Manager (deep) | Instrument context and debate history (`TradingAgents-0.5.1/tradingagents/agents/managers/research_manager.py:17-51`). | The raw reports. |
| Trader (quick) | The plan, the market report only if it is non-empty, and the portfolio (`TradingAgents-0.5.1/tradingagents/agents/trader/trader.py:29-46`). | The sentiment, news and fundamentals reports and the debate transcript; it sees the debate only as digested in the plan. |
| Portfolio Manager (deep) | The plans, the risk history, the portfolio, and lessons only when there are some (`TradingAgents-0.5.1/tradingagents/agents/managers/portfolio_manager.py:30-43`). | The raw reports. |

Tier assignment is at `TradingAgents-0.5.1/tradingagents/graph/setup.py:78-93`.

### 3. Design philosophy (as shown by the code)

1. **Absence is a state, not a blank.** The code keeps "not provided", "empty" and "failed" apart. Three examples: a missing portfolio is never treated as a flat book (`TradingAgents-0.5.1/tradingagents/agents/context.py:194-208`); a missing optional field renders as "not provided" (`TradingAgents-0.5.1/tradingagents/agents/schemas.py:200-210`); a failed Reddit fetch returns `None`, never `[]` (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/reddit.py:171-188`).
2. **Time correctness is enforced by the server, never trusted to the model.** Dates are injected and clamped, windows are half-open in UTC, and data is served at the vintage that was current on the run date (`TradingAgents-0.5.1/tradingagents/dataflows/date_window.py:1-30`, `TradingAgents-0.5.1/tradingagents/dataflows/vendors/fred.py:180-193`).
3. **Error types are defined by how the router reacts, not by what caused them:** "the number of types is the number of distinct router reactions" (`TradingAgents-0.5.1/tradingagents/dataflows/errors.py:1-16`).
4. **Configuration errors fail loudly; runtime problems degrade in the open.** A misspelled boolean raises at import (`TradingAgents-0.5.1/tradingagents/default_config.py:36-69`). An optional data category degrades to a sentinel that says it is missing (`TradingAgents-0.5.1/tradingagents/dataflows/router.py:97-102`).
5. **Code does whatever does not need an LLM:** identity resolution, date clamping, rating parsing, routing on speaker prefixes that code writes, and backtest scoring.
6. **One path for every entry point.** Settlement, lesson retrieval and decision recording happen on the graph object, not inside one entry point (`TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:260-299`).
7. **Every bug becomes a named test**, usually one that inspects the rendered prompt or the file on disk (`TradingAgents-0.5.1/tests/test_prompt_integrity.py:18-87`).
8. **Scope is stated honestly.** The backtest "is not a portfolio simulator, and must not grow one" (`TradingAgents-0.5.1/tradingagents/backtest.py:9-14`), and its summary prints what it cannot prove (`TradingAgents-0.5.1/tradingagents/backtest.py:118-122`).

### 4. Core mechanisms, ranked by value to DRF

**M1. Resolution → reflection → lesson loop, gated in time (C03, C19)**

How it works:
- **Phase A.** `store_decision` appends `[date | ticker | rating | pending]` with no LLM call. It is idempotent per (date, ticker) whether the existing entry is pending or settled. Without that, a rerun after settlement double-counted the decision (`TradingAgents-0.5.1/tradingagents/decision_log.py:30-52`).
- **Phase B.** This runs at the start of the next run for the same ticker.
  - `fetch_returns` asks for `round(h*7/5)+7` calendar days of prices. It requires more than `holding_days` bars in both the stock and the benchmark series; otherwise the entry stays pending. `resolution_date` is the date of the last bar used, i.e. when the outcome became knowable (`TradingAgents-0.5.1/tradingagents/graph/settlement.py:52-75`).
  - If the reflection call fails, the entry stays pending and the new run carries on (`TradingAgents-0.5.1/tradingagents/graph/settlement.py:107-120`).
  - All updates are written in one batch via a temp file and replace (`TradingAgents-0.5.1/tradingagents/decision_log.py:179-230`).
- **Reflection prompt.** It names the window ("may be shorter than the horizon the decision was written for"). It asks for exactly 2-4 sentences: cite the alpha, say plainly if the window is too short, say which part of the thesis is supported or undercut, and give one lesson. The model is told the text is "stored verbatim" (`TradingAgents-0.5.1/tradingagents/graph/reflection.py:11-32`).
- **Retrieval.** `get_past_context(as_of)` keeps only entries with `resolved <= as_of`. Entries without a stamp are excluded from historical queries. It returns 5 full entries for the same ticker and 3 reflections from other tickers (`TradingAgents-0.5.1/tradingagents/decision_log.py:73-110`). `as_of` equals the trade date only for historical runs (`TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:130-139`). The Portfolio Manager is the only consumer, and the lessons block is omitted entirely when empty, which is the fix for #572, fabricated lessons (`TradingAgents-0.5.1/tradingagents/agents/managers/portfolio_manager.py:38-43`, `TradingAgents-0.5.1/CHANGELOG.md:405-409`).

Why it matters for DRF. DRF already resolves forecasts:
- `due_for_resolution` (`backend/app/services/forecast_ledger.py:264-274`);
- `append_market_resolution` with `resolved_at` (`backend/app/services/forecast_ledger.py:369-399`);
- the autorun (`backend/app/services/resolution_autorun.py:38`).

It has no outcome → lesson feedback: grepping `backend/app` and `deerflow_bridge` for `past_context|reflect_on|postmortem|lessons_learned` returns nothing. Separately, `fit_recalibrator` fits on every resolved row with no as-of gate (`backend/app/services/backtest.py:188-227`; the file never references `as_of`).

Proposed transplant:
1. On resolution, run one cheap-tier reflection. It must state the scoring window versus the forecast horizon; DRF horizons are often years long.
2. Store a separate `outcome_known_at`.
3. Retrieve the top-k lessons by topic similarity, gated on `outcome_known_at <= brief.as_of`. Exclude legacy rows that lack the field.
4. Validate the reflection before storing it; TradingAgents does not.
5. Run this in the autorun rather than lazily on the next run, which avoids TradingAgents' orphaned-pending weakness (`TradingAgents-0.5.1/tradingagents/graph/settlement.py:84-95`).

**M2. As-of enforcement safe for hindcasts (C08, C18, C35)**

How it works:
- **Hidden, injected date.** Every dated tool takes `trade_date: Annotated[str, InjectedState("trade_date")] = ""`, so the parameter never appears in the schema the model sees (`TradingAgents-0.5.1/tradingagents/agents/tools.py:17-35`; tests at `TradingAgents-0.5.1/tests/test_tool_date_enforcement.py:24-133`).
- **`as_of`.** Serves the date the model asked for only if it parses and is on or before the run date; otherwise it serves the run date.
- **`as_of_window`.** Clamps the end of the window. A window lying wholly in the future keeps its span and is shifted back (`TradingAgents-0.5.1/tradingagents/dataflows/date_window.py:72-95`).
- **One window rule.** Items are kept if they fall in `[start, end+1d)` in UTC. Undated items are kept only in live windows (`TradingAgents-0.5.1/tradingagents/dataflows/date_window.py:17-30`).
- **Live-only data withheld before any request is made:** company profiles (`TradingAgents-0.5.1/tradingagents/dataflows/date_window.py:98-124`) and Polymarket odds (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/polymarket.py:86-91`). Instrument identity carries a caveat that it describes the instrument today (`TradingAgents-0.5.1/tradingagents/agents/context.py:146-152`).
- **Leak tests.** No notice explaining withheld or unavailable data may name a date after the cutoff, and a historical output may not contain `date.today()` (`TradingAgents-0.5.1/tests/test_undated_tools_as_of.py:252-303`).

Why it matters for DRF. DRF has the building blocks: `VALIDATE_AS_OF_DATE` (`backend/app/config.py:477`), `RESEARCH_ASOF_MAX_LAG_DAYS` (`backend/app/config.py:513`) and `parse_as_of` (`backend/app/utils/dates.py:38-45`). What it lacks is date injection and clamping at the tool boundary (C08 status: absent). Without that, backtests of historical questions leak.

Polymarket in DRF: the anchor filter drops closed markets and prices of exactly 0 or 1 (`deerflow_bridge/market_tools.py:187-191`). It stores `endDate` as a field only (`deerflow_bridge/market_tools.py:207`) and never rejects a market whose end date has passed. For past-as-of runs DRF should use price history (`backend/app/utils/prediction_markets.py:420`) or withhold the anchor.

**M3. Honest decision parsing: REVIEW sentinel and per-field coercion (C01)**

How it works:
- `extract_rating` applies NFKC normalization, so the fullwidth `：` matches.
- It skips lines that echo a "rating scale/options/legend" and keeps the **last** labelled rating whose value is in the scale.
- With no label, it accepts a tier word only if exactly one distinct tier appears (`TradingAgents-0.5.1/tradingagents/agents/rating.py:49-78`).
- `parse_rating` defaults to `REVIEW` (`TradingAgents-0.5.1/tradingagents/agents/rating.py:81-93`).
- The same function feeds the signal (`TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:388-390`), the log tag (`TradingAgents-0.5.1/tradingagents/decision_log.py:48-50`), the backtest (where REVIEW counts as unscored; `TradingAgents-0.5.1/tradingagents/backtest.py:186-201`) and a CLI warning (`TradingAgents-0.5.1/cli/run.py:359-366`).
- Optional numeric fields are coerced one at a time. Placeholders, `%` and ranges become `None`, so one bad field no longer sinks the whole object (`TradingAgents-0.5.1/tradingagents/agents/schemas.py:26-58`).

Why it matters for DRF. DRF has the same "silent Hold" bug in probability form. `_coerce_float` cannot parse `"30%"` (`backend/app/services/forecast_extractor.py:59-66`), and `_normalize_scenarios` then writes `0.0` (`backend/app/services/forecast_extractor.py:80`) before renormalizing.

The fix should be type-aware:
- `%` in a probability field can be salvaged by dividing by 100;
- a range gets a flag;
- missing or ambiguous values get `NEEDS_REVIEW`, which is excluded from Brier, the ledger and the ensemble, and surfaced by the publish gate.

Copy the parser's order of operations, not its exact regex (see §5).

**M4. What absence means: markers, coverage gaps, failed versus empty (C04, C12)**

How it works:
- **Markers.** An empty opponent turn reads "(The {opponent} has not spoken yet — open the debate with your own case.)". A missing report reads "(No {source} report in this run: it is not available, not an empty finding.)" (`TradingAgents-0.5.1/tradingagents/agents/context.py:33-44`, `TradingAgents-0.5.1/tradingagents/agents/context.py:180-191`).
- **Conditional instructions.** An instruction that depends on missing data is removed together with the data: the Trader's price-grounding line (`TradingAgents-0.5.1/tradingagents/agents/trader/trader.py:34-46`) and the PM's lessons line (`TradingAgents-0.5.1/tradingagents/agents/managers/portfolio_manager.py:38-43`).
- **`coverage_gap`.** Absence is claimed only when coverage reaches the first day of the window and the window ends by today. A merged or relevance-ranked result passes no dates, so only the present bounds its coverage (`TradingAgents-0.5.1/tradingagents/dataflows/date_window.py:38-62`).

Why it matters for DRF. DRF's gateway already separates "no results" from "search unavailable" (`deerflow_bridge/research_gateway.py:3358-3359`). Web search, however, is relevance-ranked, so "none found" almost never proves absence. `report_lint` should flag absence claims ("no reported talks") whose only support is an unobserved search.

Every optional slot should state which of three states it is in: not run, ran and found nothing, or failed. Examples: Polymarket anchors, sim signal for an actor, research track, critique slots (`backend/app/services/report_agent.py:9497-9523`). DRF is bilingual, so the markers need zh and en variants.

**M5. Typed failure taxonomy and router sentinels (C05, C44)**

How it works:
- There are three error types: `NoMarketDataError`, `VendorRateLimitError`, and `VendorNotConfiguredError` (which is also a `ValueError`) (`TradingAgents-0.5.1/tradingagents/dataflows/errors.py:21-55`).
- The router treats the configured chain as the exact chain, with no silent fallback (#988/#289). Every non-typed error is logged (#989). Results are decided in this order:
  1. `NO_DATA_AVAILABLE … Do not estimate or fabricate values`;
  2. `DATA_UNAVAILABLE … says nothing about the instrument`;
  3. for the optional categories (`macro_data`, `prediction_markets`), log a warning and return a `DATA_UNAVAILABLE … Proceed without it; do not fabricate values` sentinel;
  4. otherwise re-raise (`TradingAgents-0.5.1/tradingagents/dataflows/router.py:184-291`).
- An outage probe runs only when a result is empty (`TradingAgents-0.5.1/tradingagents/dataflows/net.py:27-37`).
- The Alpha Vantage date trim is deliberately left unguarded, so a parse failure raises instead of serving future bars (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/alpha_vantage/common.py:140-143`).

Why it matters for DRF. This gives research tools the core-versus-optional split DRF's philosophy already calls for ("degrade-safe" enrichment, "fail-closed" evidence). It also gives separate telemetry counters for "source down" and "no hits".

**M6. Structured data at the right vintage, with the date semantics disclosed (C06, C27)**

How it works:
- **FRED.** Both the metadata and the observations requests set `realtime_start = realtime_end = min(curr_date, FRED's Chicago today)` (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/fred.py:20-28`, `TradingAgents-0.5.1/tradingagents/dataflows/vendors/fred.py:180-193`). An alias table rejects LLM prose before any API call (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/fred.py:102-122`).
- **SEC EDGAR, as filed** (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/sec_edgar.py:77-83`, `TradingAgents-0.5.1/tradingagents/dataflows/vendors/sec_edgar.py:147-184`):
  - only facts with `filed <= curr_date` count;
  - the first tag that reports a period owns it, and values are never summed across tags;
  - duration spans must be 60-115 days (quarterly) or 300-400 days (annual);
  - annual columns are gated on 10-K/20-F/40-F filings;
  - for each period, the latest filing on or before the date wins.
  
  The module docstring gives the example that Apple's 2008 assets read 39.6B until the 2010 amendment (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/sec_edgar.py:1-16`).
- **Vintage headers.** Output states its date semantics, for example "Periods are cut at the fiscal period end" and "Rows are dated by transaction date … up to two business days later" (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/yahoo/fundamentals.py:92-117`, `TradingAgents-0.5.1/tradingagents/dataflows/vendors/yahoo/fundamentals.py:147-155`).

Why it matters for DRF. DRF has no macro or filings tool (C06 status: absent). Its `quantitative_facts` already carry `as_of_date/period_end/value_type` (`deerflow_bridge/linear_research.py:474`). Adding a `date_semantics` field (published / filed / period_end / revised / estimate) and rendering it would stop the report from treating an estimate or a period-end number as known on a given date.

**M7. A deterministic "verified snapshot" as the source of truth (C11)**

How it works:
- Values come as reported, via `fill_gaps=False`.
- The date cutoff is re-applied because a verification path "must not trust its input".
- The indicator set is fixed, and each indicator gets its own `try`.
- The snapshot ends with: treat these as exact numbers, and "flag the discrepancy rather than inventing a reconciled number" (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/yahoo/snapshot.py:1-125`).

Why it matters for DRF. Build a verified-facts block from FRED, EDGAR, Polymarket and extracted facts, and have `report_lint` check each prose number against it. TradingAgents enforces this only through the prompt.

**M8. Information walls and keeping evidence apart from verdicts (C14)**

How it works:
- Analysts are forbidden from emitting a trade call. A test bans `FINAL TRANSACTION PROPOSAL` in analyst source (`TradingAgents-0.5.1/tests/test_prompt_integrity.py:36-44`).
- The researchers are blind to the book (`TradingAgents-0.5.1/tests/test_portfolio_context.py:153-159`) and size their recommendations "relative to a standard allocation" (`TradingAgents-0.5.1/tradingagents/agents/schemas.py:120-127`).
- The judges are told to weigh arguments "independent of which side spoke first or last" (`TradingAgents-0.5.1/tradingagents/agents/managers/research_manager.py:36`).

Why it matters for DRF. DRF should keep the dossier and the sim signal pack free of final probabilities. The independent estimate should stay blind to Polymarket prices and prior forecasts until the anchoring step. Enforce this with tests that capture the rendered prompt; TradingAgents relies on source grep (§5).

**M9. Symmetric anti-hedge rule (C20)**

How it works:
- The Research Manager's wording: "conflict alone is not a reason to Hold. Commit to the side with the stronger case, sized by how decisively it wins. Choose Hold only when the evidence is still balanced after that weighing, or too thin to support a call; do not manufacture a direction to appear decisive" (`TradingAgents-0.5.1/tradingagents/agents/managers/research_manager.py:36`). The Portfolio Manager says "do not force a direction", and the schema fields say "Conflicting arguments alone are not a reason to Hold: commit to the stronger side".
- It appears in the schema field descriptions, which the structured-output path sees, and in the prompt bodies, which the free-text path sees (`TradingAgents-0.5.1/tradingagents/agents/schemas.py:104-111`, `TradingAgents-0.5.1/tradingagents/agents/schemas.py:230-239`, `TradingAgents-0.5.1/tradingagents/agents/managers/portfolio_manager.py:69`).
- A parametrized test checks all four sites and bans the regressed wording "materially conflicting" (#1321) (`TradingAgents-0.5.1/tests/test_structured_agents.py:492-506`).

Why it matters for DRF. For probabilities the wording becomes: "disagreement alone is not a reason to sit at 50% / the base rate; move by how decisively one side wins; do not manufacture extremity". DRF should also measure how much ledger mass sits near 0.5, which TradingAgents never did.

**M10. Structured output with a dual contract (C10)**

How it works:
- The schema is bound once. A `None` parse counts as a miss (#1051), and there is one retry as free text with the same prompt (`TradingAgents-0.5.1/tradingagents/agents/structured.py:43-89`).
- `NO_EXTERNAL_TOOLS` is added because binding only the schema exposes a single tool, and a model primed toward tools calls `web_search` and loses the typed output (#1130) (`TradingAgents-0.5.1/tradingagents/agents/structured.py:27-39`).
- The prompt body includes a `## Output` section, so that providers without structured output still produce parseable text (`TradingAgents-0.5.1/tradingagents/agents/managers/research_manager.py:43-51`, `TradingAgents-0.5.1/tests/test_rating_integrity.py:170-212`).

Why it matters for DRF. DRF asks for `json_object` (`backend/app/utils/llm_client.py:586-592`). DRF should adopt the output contract in the prompt body and the None-counts-as-miss rule. For forecast numbers, replace TradingAgents' fallback to free text (it logs a warning, then retries once unstructured: `TradingAgents-0.5.1/tradingagents/agents/structured.py:82-89`) with a repair retry that fails closed, and count how often it fires.

**M11. Bull/Bear debate and risk panel (C09). Moderate value, unproven.**

How it works:
- Speaker prefixes are written by code, not the model (`TradingAgents-0.5.1/tradingagents/agents/researchers/bull_researcher.py:53`, `TradingAgents-0.5.1/tradingagents/agents/risk_mgmt/aggressive_debator.py:50-57`). Routers terminate on a count (`2R` for the debate, `3R` for risk). Every edge shares the full path map (`TradingAgents-0.5.1/tradingagents/graph/conditional_logic.py:12-33`, `TradingAgents-0.5.1/tradingagents/graph/setup.py:26-40`).

Why it matters for DRF. It is only an option, and should be:
- off by default and behind a flag;
- limited to the top-N binary questions;
- run with advocates who must cite `[S#]`;
- judged by a facilitator who writes a `{pro, con, unresolved, source_refs}` ledger rather than moving probabilities;
- kept only if `golden_eval` improves.

The final pool stays deterministic (`backend/app/services/ensemble.py:118`), and `self_critique_forecast` stays humility-monotone (`backend/app/services/forecast_extractor.py:3588-3590`).

**M12. Resume key that includes the run's shape (C29)**

How it works:
- The signature is `analysts=…|debate=N|risk=N|asset=X|portfolio=<sha256[:12] or none>` (`TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:141-155`, `TradingAgents-0.5.1/tradingagents/portfolio.py:53-55`). It is folded into `sha256(...)[:16]` (`TradingAgents-0.5.1/tradingagents/graph/checkpointer.py:28-38`).
- On resume the graph is fed `None`, because re-passing the initial state duplicates messages (`TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:211-219`).
- The checkpoint is cleared under the same key.
- An end-to-end test asserts `resumed_calls == full_calls - (fail_at - 1)` (`TradingAgents-0.5.1/tests/test_graph_end_to_end.py:141-156`).

Why it matters for DRF. Fold every setting that changes results into the identity of the handoff manifest, and include model ids and prompt/engine versions, which TradingAgents leaves out. Add a test that counts LLM calls on resume.

**M13. Backtest harness (C40)**

How it works:
- Each run gets an isolated log under `results/backtest/<run_id>`.
- Cells already in the log are skipped, so rerunning resumes.
- Failures are isolated per cell, and there is an explicit final settlement pass (`TradingAgents-0.5.1/tradingagents/backtest.py:128-175`).
- Scoring is direction-aware: a Sell that trails the benchmark (negative alpha) is a hit, and Hold gets no hit rate (`TradingAgents-0.5.1/tradingagents/backtest.py:87-89`, `TradingAgents-0.5.1/tradingagents/backtest.py:193-199`).
- The caveats are rendered with the results (`TradingAgents-0.5.1/tradingagents/backtest.py:105-125`).

Why it matters for DRF. DRF already isolates evaluation ledgers (`backend/app/services/forecast_ledger.py:38`). Add resume-by-skip, a list of failures, and self-stated caveats (single sample, sources not archived, the window used).

**M14. A hermetic test suite that enforces invariants (C22)**

How it works:
- `TRADINGAGENTS_*` variables are blanked before import, so `load_dotenv` cannot inject them.
- An autouse fixture refuses socket connections unless a test is marked `integration`.
- Placeholder keys are filled with `or`, so blank values are covered too.
- Global config is reset around every test (`TradingAgents-0.5.1/tests/conftest.py:9-90`).
- Also present: capture of the rendered prompt through fake LLMs, a scripted `BaseChatModel` end-to-end test that asserts the exact set of vendor calls (`TradingAgents-0.5.1/tests/test_graph_end_to_end.py:27-169`), and AST layering tests (`TradingAgents-0.5.1/tests/test_layering.py:12-35`).

Why it matters for DRF. DRF takes clients offline one at a time (`backend/tests/conftest.py:56-91`) and has no socket-level guard. Add one, with a localhost allowlist for FalkorDB, plus date-leak scans for as-of runs.

**M15. Config discipline (C13, C39)**

How it works:
- `_coerce` coerces by the type of the default and accepts a closed boolean vocabulary. Errors are raised as `Invalid value for <ENV>`. A blank value means unset (`TradingAgents-0.5.1/tradingagents/default_config.py:36-75`).
- `run_config` uses a ContextVar so concurrent graphs cannot read each other's vendors (#1369) (`TradingAgents-0.5.1/tradingagents/dataflows/config.py:10-61`).

Why it matters for DRF. `backend/app/config.py` has 165 lines using `.strip().lower() == 'true'`, including `PIPELINE_HEALTH_GATE` (`backend/app/config.py:167`) and `REPORT_PUBLISH_GATE` (`backend/app/config.py:178`). Under that idiom "1", "yes" or a typo silently switches off honesty gates that default to on. DRF should add a shared `_env_bool` that raises on anything outside the vocabulary.

**M16. LLM transport tables (C23, C41, C43)**

How it works:
- A frozen `ModelCapabilities` is resolved by exact id, then regex, then default, stripping only the official `deepseek/` namespace (`TradingAgents-0.5.1/tradingagents/llm_clients/capabilities.py:93-135`).
- A `ProviderSpec` registry holds per-provider settings (`TradingAgents-0.5.1/tradingagents/llm_clients/openai_client.py:183-234`), and native-OpenAI detection parses the hostname (`TradingAgents-0.5.1/tradingagents/llm_clients/openai_client.py:242-255`).
- Reasoning knobs are dropped or remapped by version (`TradingAgents-0.5.1/tradingagents/llm_clients/anthropic_client.py:14-38`, `TradingAgents-0.5.1/tradingagents/llm_clients/google_client.py:58-66`).
- DeepSeek's `reasoning_content` is round-tripped, and MiniMax's `reasoning_split` is sent via `extra_body` (`TradingAgents-0.5.1/tradingagents/llm_clients/openai_client.py:71-162`).
- The Qwen picker offers only versioned model ids, because the version-less aliases auto-upgrade (`TradingAgents-0.5.1/tradingagents/llm_clients/model_catalog.py:36-45`).

Why it matters for DRF. DRF's quirks are written inline:
- a regex strips `<think>` (`backend/app/utils/llm_client.py:838-840`);
- Kimi temperature is coerced (`backend/app/utils/llm_client.py:842-855`);
- per-provider bodies disable thinking (`backend/app/config.py:799-806`).

A capability row per model would centralize all of these. Log any knob that gets dropped; TradingAgents drops them silently. Probe `reasoning_split` live before enabling it on MiniMax-M3: TradingAgents lists "Coding Plan" models among those that reject the flag (`TradingAgents-0.5.1/tradingagents/llm_clients/capabilities.py:40-45`), and DRF reaches MiniMax through the coding plan (`backend/app/config.py:740`).

**M17. Small tricks worth taking**
- **Anchored placeholder after a reset**, never a bare "Continue", which some providers took literally (#888) (`TradingAgents-0.5.1/tradingagents/agents/context.py:211-235`). C28.
- **Identity card** resolved once, failing open, with "do not substitute … unless a tool result explicitly disproves" plus a vintage caveat (`TradingAgents-0.5.1/tradingagents/agents/context.py:55-77`, `TradingAgents-0.5.1/tradingagents/agents/context.py:99-159`). C37.
- **I/O hygiene** (C38):
  - path components allow-listed, with dot-only values rejected (`TradingAgents-0.5.1/tradingagents/dataflows/symbols.py:147-180`);
  - the key is scrubbed and the error re-raised outside the `except` block, so no chain holds the URL (`TradingAgents-0.5.1/tradingagents/dataflows/net.py:6-24`);
  - `.env` is created `0600` with `O_EXCL`, then `chmod` before writing (`TradingAgents-0.5.1/cli/prompts.py:588-639`).
- **Tools declared in one tuple** that feeds both the prompt and the ToolNode, with the injected argument hidden (`TradingAgents-0.5.1/tradingagents/agents/analysts/market_analyst.py:6-11`, `TradingAgents-0.5.1/tradingagents/agents/analysts/market_analyst.py:72-76`, `TradingAgents-0.5.1/tradingagents/agents/tools.py:1-22`). C34.
- **Screening** (C36): a post is dropped only when its relevance is below 0.3, and a stance counts only when confidence is at least 0.5 (`TradingAgents-0.5.1/tradingagents/agents/post_screen.py:36-38`). On any failure all posts are kept under a visible "unscreened" banner, and queued requests are cancelled with `cancel_futures` (`TradingAgents-0.5.1/tradingagents/agents/post_screen.py:155-174`).
- **Clean-install import smoke test** in CI (#994) (`TradingAgents-0.5.1/.github/workflows/ci.yml:46-52`). C47.

### 5. Commodity, weak or buggy: do not copy

- **Commodity.** LangGraph plumbing, the yfinance and Alpha Vantage wrappers, the Rich CLI, questionary prefs, Docker.
- **Rating parser edge cases.** I checked these read-only by running the module's own `extract_rating`:
  - `"**Rating**: Buy … prior rating - Sell"` returns `Sell`, because the last label wins over the real first-line rating;
  - `"sell-off"` returns `Sell`;
  - `"Credit rating: Hold steady"` returns `Hold`.
  
  Code: `TradingAgents-0.5.1/tradingagents/agents/rating.py:64-78`. The docstring still says "first standalone" (`TradingAgents-0.5.1/tradingagents/agents/rating.py:55`).
- **Debate framing.**
  - The Aggressive debater must "create a compelling case for the trader's decision" even if the trader said Sell (`TradingAgents-0.5.1/tradingagents/agents/risk_mgmt/aggressive_debator.py:36`).
  - The Neutral debater is primed that the middle is "the best of both worlds" (`TradingAgents-0.5.1/tradingagents/agents/risk_mgmt/neutral_debator.py:46`).
  - The judges never see the raw reports, so a number a debater invents cannot be checked (`TradingAgents-0.5.1/tradingagents/agents/managers/research_manager.py:17-51`).
  - A stale "3 rounds" comment remains (`TradingAgents-0.5.1/tradingagents/graph/conditional_logic.py:17`).
- **Capability table has drifted from the catalog.** The catalog's DeepSeek pick `deepseek-flash` (`TradingAgents-0.5.1/tradingagents/llm_clients/model_catalog.py:156-166`) has no row in the table, so it resolves to `_DEFAULT` and gets `tool_choice` (`TradingAgents-0.5.1/tradingagents/llm_clients/capabilities.py:94-135`).
- **An explicit `api_key` cannot stand in for the environment variable.** The required-key check reads only the environment and raises before the passthrough loop runs, so an explicit key is used only when the env var is also set (`TradingAgents-0.5.1/tradingagents/llm_clients/openai_client.py:303-331`). Conftest placeholders hide this (`TradingAgents-0.5.1/tests/conftest.py:66-71`).
- **Tests that never run.** Classes named `NativeBaseUrlTests` and `ResponsesApiSelectionTests` lack the `Test` prefix, so pytest does not collect them (`TradingAgents-0.5.1/tests/test_openai_responses_base_url.py:15`, `TradingAgents-0.5.1/tests/test_openai_responses_base_url.py:31`).
- **Settlement.**
  - Stock and benchmark are aligned by position, not by date (`TradingAgents-0.5.1/tradingagents/graph/settlement.py:69-71`).
  - Only same-ticker entries are settled, and pending entries never expire (`TradingAgents-0.5.1/tradingagents/graph/settlement.py:84-95`).
  - Log appends (`TradingAgents-0.5.1/tradingagents/decision_log.py:48-52`) race with the read-modify-replace path (`TradingAgents-0.5.1/tradingagents/decision_log.py:160-177`), with no lock and a fixed `.tmp` name. DRF's `flock` is already better (`backend/app/services/forecast_ledger.py:360`).
- **Resume signature leaves out** models, provider and language (`TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:141-155`).
- **Router precedence.** "No data" outranks "unavailable", so a mixed chain can falsely call an instrument "invalid, delisted" (`TradingAgents-0.5.1/tradingagents/dataflows/router.py:245-266`). The outage probe ignores HTTP status, so a 403/429 block counts as reachable (`TradingAgents-0.5.1/tradingagents/dataflows/net.py:27-37`).
- **OHLCV look-ahead.** `auto_adjust=True` rescales past prices using today's split and dividend factors, and this reaches the "verified" snapshot too, which loads its rows through `load_ohlcv` (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/yahoo/ohlcv.py:249`, `TradingAgents-0.5.1/tradingagents/dataflows/vendors/yahoo/snapshot.py:37`). History covers only 5 years (`TradingAgents-0.5.1/tradingagents/dataflows/vendors/yahoo/ohlcv.py:215-221`).
- **Sentiment inputs are not point-in-time**, which the code admits (`TradingAgents-0.5.1/tradingagents/agents/analysts/sentiment_analyst.py:10-13`).
- **Config contradictions.** A comment says "debate stays in English" (`TradingAgents-0.5.1/tradingagents/default_config.py:111-112`) while the language directive is applied to debaters (`TradingAgents-0.5.1/tradingagents/agents/context.py:17-30`). A global `set_config` still runs in `__init__` (`TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:65`).
- **Unvalidated outputs.** The free-text fallback is unvalidated, catches every exception, and is not counted (`TradingAgents-0.5.1/tradingagents/agents/structured.py:73-89`). The reflection is stored without validation (`TradingAgents-0.5.1/tradingagents/graph/reflection.py:34-61`).

### 6. Lessons from the CHANGELOG and tests

- **Silent Hold (#1170).** An unparseable rating became a tradeable Hold and was quoted back to later runs. Now it is REVIEW everywhere, the labelled rating decides, and several unlabelled tiers mean review (`TradingAgents-0.5.1/CHANGELOG.md:149-151`, `TradingAgents-0.5.1/CHANGELOG.md:66`, `TradingAgents-0.5.1/CHANGELOG.md:111`, `TradingAgents-0.5.1/CHANGELOG.md:81`).
- **Debate-opening fabrication (#1176).** Filling an empty opponent slot made the model invent a rebuttal (`TradingAgents-0.5.1/CHANGELOG.md:146-148`).
- **Hold trigger (#1321).** A Hold condition that conflicting arguments satisfy fired on every run, because every debate contains conflict (`TradingAgents-0.5.1/tests/test_structured_agents.py:499-506`).
- **Lesson look-ahead (#1251)** and **premature settlement (#1169)** (`TradingAgents-0.5.1/CHANGELOG.md:135-141`).
- **FRED vintage leak (#1275)**, **undated social feeds (#1220)**, **live profiles (#1300)**, and **dates omitted or later than the run reaching vendors (#1331/#1319/#1118)** (`TradingAgents-0.5.1/CHANGELOG.md:128-134`, `TradingAgents-0.5.1/CHANGELOG.md:70`, `TradingAgents-0.5.1/CHANGELOG.md:77`).
- **A filter that never ran.** The Alpha Vantage look-ahead filter was skipped because the payload was a JSON string, not a dict (#1115) (`TradingAgents-0.5.1/CHANGELOG.md:185-187`).
- **"Unavailable is not absent"** applied across news, Reddit and StockTwits. An outage is no longer reported as "company has no data" (`TradingAgents-0.5.1/CHANGELOG.md:72`, `TradingAgents-0.5.1/CHANGELOG.md:75`).
- **Notices leaking dates.** A historical run was told today's date through its notices (`TradingAgents-0.5.1/CHANGELOG.md:40`).
- **One entry-point path.** The CLI skipped settlement, lessons and recording until both entry points shared `create_run_state` (settlement and lessons) and `record_decision` (recording) (`TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:260-272`, `TradingAgents-0.5.1/tradingagents/graph/trading_graph.py:291-299`). `--checkpoint` did nothing on the CLI (#1249) (`TradingAgents-0.5.1/CHANGELOG.md:152-155`).
- **Resuming the wrong graph (#1089).** A resume under a different analyst set continued the wrong graph. Clearing under a key that did not match replayed old decisions (`TradingAgents-0.5.1/tests/test_portfolio_context.py:162-188`).
- **Prompt integrity.**
  - A trailing comma turned a brief into a tuple repr (`TradingAgents-0.5.1/tests/test_prompt_integrity.py:18-33`).
  - Unused "FINAL TRANSACTION PROPOSAL" requests leaked direction as evidence (`TradingAgents-0.5.1/tests/test_prompt_integrity.py:36-44`).
  - The prompt/tool signature drifted (#1116).
  - The language directive was missing (#740/#801).
- **Grounding downstream deciders.** They need raw evidence, not just digests: the Trader now also gets the market report (#1167) (`TradingAgents-0.5.1/CHANGELOG.md:159-161`).
- **Config.** Misspelled booleans used to mean False, now they raise. Blank paths keep the default. Configs leaked across graphs (#1369) (`TradingAgents-0.5.1/tests/test_env_overrides.py:129-131`, `TradingAgents-0.5.1/CHANGELOG.md:37`, `TradingAgents-0.5.1/CHANGELOG.md:45`).
- **Test hermeticity (#1368/#1372).** A live Reddit 429 once turned a test file into a multi-minute hang (`TradingAgents-0.5.1/tests/test_structured_agents.py:440-443`, `TradingAgents-0.5.1/CHANGELOG.md:47`).

### 7. Paper claims versus the code

- **"Analysts run concurrently."** The code runs a strict sequential chain (`TradingAgents-0.5.1/tradingagents/graph/setup.py:112-125`), and the concurrency knob was removed as a no-op (#979) (`TradingAgents-0.5.1/CHANGELOG.md:269-270`).
- **"Analysts, researchers and traders use deep-thinking models."** Only the Research Manager and Portfolio Manager are deep; every other role is quick (`TradingAgents-0.5.1/tradingagents/graph/setup.py:78-93`).
- **"A facilitator sets the debate rounds."** The number of rounds comes from config, default 1 each (`TradingAgents-0.5.1/tradingagents/graph/conditional_logic.py:7-21`).
- **"Technical analyst executes code; sentiment from Reddit/X with LLM scores."** The market analyst has three data tools and no code execution (`TradingAgents-0.5.1/tradingagents/agents/analysts/market_analyst.py:6-11`). Sentiment uses pre-fetched Yahoo news, StockTwits and Reddit RSS, with optional Jev screening and no X (`TradingAgents-0.5.1/tradingagents/agents/analysts/sentiment_analyst.py:1-18`).
- **"A reflective agent is pivotal."** The paper never defines one. In the code, the Reflector exists only for deferred settlement feeding the PM (`TradingAgents-0.5.1/tradingagents/graph/settlement.py:84-132`).
- **"Fund Manager approves execution."** There is no execution. The backtest refuses to simulate a portfolio (`TradingAgents-0.5.1/tradingagents/backtest.py:9-14`).
- **"No look-ahead."** The CHANGELOG records a run of look-ahead leaks found and fixed in 0.3.1–0.5.1 (2026-07 to 2026-09), all after the paper's June 2025 revision (see §6). Whether the paper's backtest code shared those paths cannot be checked from this repo, so treat the claim as unverified.
- **Structured state instead of long message histories.** The code matches this: reports live in state keys and messages are wiped between analysts (`TradingAgents-0.5.1/tradingagents/agents/context.py:211-235`). Debate transcripts, however, are still unbounded concatenated strings (`TradingAgents-0.5.1/tradingagents/agents/state.py:1-77`).
- **The evidence behind the results is thin:** 3 months, 3 tickers reported, a single run, no costs, rule-based baselines only, and no ablation. Do not cite it as evidence that debate helps.
- **Trading-R1**, which the README links, is methodology only for DRF. It suggests volatility-normalized thresholds as base-rate anchors (C24: value 2, one refutation). Its R0 post-mortem warns that structural gates can be gamed, so DRF gates should be paired with substance checks.

### 8. What DRF should take, and what it should not

| Value | Candidate | What to take from TradingAgents | Where it lands in DRF |
|---|---|---|---|
| 4 | C03 | Reflection on resolution, stamped `outcome_known_at`, lessons gated by as-of, block omitted when empty | `resolution_autorun`, `forecast_ledger`, report spine, `fit_recalibrator` |
| 4 | C08, C18 | Injected hidden as-of date, clamping, the half-open UTC window, withholding live-only data, leak-scan tests | `research_gateway` / `linear_research` tools, backtest mode |
| 4 | C11 | Deterministic verified-facts block with the "flag, don't reconcile" rule, plus a lint check | report writer, `report_lint.py` |
| 4 | C14 | Evidence producers never emit verdicts; the independent estimate is blind to anchors; enforced by rendered-prompt tests | research, sim signal pack, spine |
| 4 | C27 | Vintage / date-semantics field on facts, rendered in the report | `quantitative_facts` (`deerflow_bridge/linear_research.py:474`) |
| 3 | C01 | REVIEW / NEEDS_REVIEW sentinel; type-aware coercion one field at a time | `backend/app/services/forecast_extractor.py:59-80` |
| 3 | C04, C12 | Three-state absence markers (zh/en); coverage-aware absence claims | report and persona prompts, lint |
| 3 | C05, C44 | Typed failure taxonomy, sentinels saying "do not fabricate", outage probe with a status check, filters that fail closed | gateway, `market_tools` |
| 3 | C06 | FRED/ALFRED macro and EDGAR as-filed tools | research tools |
| 3 | C35 | Reject markets whose end date has passed; withhold live odds, or use history, for past as-of dates | `deerflow_bridge/market_tools.py:187-207` |
| 3 | C20, C10 | Symmetric anti-hedge wording in the prompt and the schema; output contract in the prompt body; None counts as a miss | spine, extractor |
| 3 | C09 | Cited pro/con debate as a default-off experiment, kept only if `golden_eval` improves | spine |
| 3 | C13, C39 | Strict `_env_bool`; run config scoped by ContextVar | `backend/app/config.py` |
| 3 | C22 | Socket refusal, blanking env before import, rendered-prompt capture, check that every test file collects tests | `backend/tests/conftest.py` |
| 3 | C23, C41, C43 | Capability rows, logged knob drops, pinned versioned ids | `llm_client.py` |
| 3 | C29, C40, C19, C36, C37, C38, C17, C34 | Resume signature, sweep harness, idempotent ledger, screening banners, identity cards, I/O hygiene, `Retry-After: 0` handling and body caps, one-source tool tuples | various |
| 2 | C24, C28, C46, C47 | Volatility-unit thresholds, anchored reset placeholder, progress counted only when a section is finalized, clean-install smoke | as noted |

**Do not take:**
- **The trading-desk role hierarchy wholesale.** The paper counts 11 LLM calls and 20+ tool calls per decision, with no ablation behind the gain. DRF's spine already keeps evidence apart from verdict.
- **A silent free-text fallback, or any LLM "risk manager", that moves probabilities.** Pooling stays deterministic (`backend/app/services/ensemble.py:118`).
- **The markdown decision log as storage.** DRF's JSONL ledger with `flock` is stronger; take only the stamp and idempotency rules.
- **Lazy settlement on the next same-topic run.**
- **Knob drops that happen silently, walls that exist only as source grep, and absence markers in English only.**
- **Social feeds, the paid Jev API, and yfinance OHLCV with `auto_adjust`.**
- **The rating regex as written.** Anchor on a dedicated first-line field instead.
- **The paper's performance figures, in any DRF document.**

## FinanceHarness (paper)

*Xiao et al., Google Cloud AI Research and UCLA, arXiv 2607.27853v2 (key FHP). Released code examined: `/Users/rogerlin/Downloads/finharness/FinanceHarness-0.1.0`. DRF anchors are relative to `/Users/rogerlin/Downloads/DeepResearchForecast` at `1e40844`. Where a statement is my own arithmetic or a reading of a figure, it says so.*

### 1. Essence

Financial research reports have to reason about what happens next. If an agent is graded on the live web, it can read the outcome, and a single LLM-judge score mixes two skills: finding the facts and anticipating what came later.

The paper makes two ideas work:
- **A point-in-time (PIT) contract.** Search returns only documents published on or before the question's cutoff, and any detected leak invalidates the run instead of lowering its score. Tools, evaluation and RL rollouts all share this contract (FHP p.4-5 §3.1, p.7 §3.3, p.9 §4.2).
- **A two-tier rubric per question.** Pre-cutoff items score evidence retrieval. Post-cutoff items score whether the report anticipated outcomes that could only be checked later (FHP p.5 §3.2, p.7 Eq.2).

The FinanceHarness agent (tiered tools, skills, citation finalizer, grounding review, recovery) is competent engineering, but its measured value is mostly retrieval. On a fixed 27B backbone, most of the 25.3 to 32.4 gain comes from pre-cutoff items (FHP p.13 Table 4). All 18 systems score only 5.2–12.8% on post-cutoff items (FHP p.12 Table 2).

For DRF, the paper matters mainly as a source of evaluation method. DRF bets on the simulation and report stages for exactly the forward-looking judgment FHP finds unsolved, yet DRF has no instrument that could show whether that bet pays off. Its 30 golden questions all resolved between 2024-01-10 and 2025-02-09, inside the training data of every current backbone (`backend/tests/eval/golden_questions.json:2-17`).

### 2. Method at a glance

Pipeline: corpus → dated finance entity graph → situations → (situation, cutoff) → question + thesis + two-tier rubric → LLM gates → ILP → expert review → FinanceGym. The agent then runs against the PIT API and a per-criterion judge scores its report.

| Layer | Component | What it does | Anchor |
|---|---|---|---|
| Benchmark | PIT sandbox | 100M+ web articles dated with htmldate, text via trafilatura, embedded with Qwen3-Embedding-4B, indexed in FAISS IVF-SQ8. The API returns only `pub_date <= cutoff`; there is no live web. | FHP p.4-5 §3.1; FHP p.7 §3.3 |
| | Entity graph | LLM-extracted triples, each carrying source URL and publication date. 5.74M edges filtered to 4.37M; 1.11M entities. | FHP p.5 §3.2 |
| | Situation miner | Three modes: cross-category linkage chains, narrative arcs around high-degree entities, polar divergences (upgrade vs downgrade, beat vs miss). An entity budget limits how often one name is sampled. | FHP p.5 §3.2 |
| | Cutoff selection | score(d) = z(volume) × (1 + entity diversity) × (1 + relation entropy / 10) | FHP p.5 Eq.1 |
| | Record generation | Generated without category priming: question, reference thesis, pre- and post-cutoff rubric. The taxonomy is labelled afterwards, bottom-up. | FHP p.5-6 §3.2 |
| | Curation | LLM gates cut 29,669 generations to 2,078; an ILP picks 500; vendor experts pass 411 (82%). Released: 400 questions, 2,464 items. Rubrics stay private. | FHP p.6-7 §3.2; FHP p.9 §5.1 |
| | Evaluation contract | Gemini-3.5-Flash judge scores each criterion 0–4 on anchored levels, seeing pre- and post-cutoff evidence. Scores are normalized per question and reported with bootstrap SE (n=1000). | FHP p.7 Eq.2; FHP p.10 §5.3 |
| Harness | Serving layer | Swappable backbone plus a lighter reader model. | FHP p.8 §4.1 |
| | Runtime control plane | Bounded loop, schema validation, result chaining, recovery and budgets. Contains no model logic. | FHP p.8 §4.1 |
| | Tool tiers | Core tools always loaded; deferred tools listed in a catalog and loaded on commit; an MCP/CLI extension tier. | FHP p.8 §4.1 |
| | Modes and skills | Modes are prompt variants over one constant tool registry. SKILL.md recipes are routed by description. | FHP p.8-9 §4.1 |
| | Grounding and guardrails | Composed citations, citation retrofit, one attribute-or-soften review pass, URL pre-fetch, search-budget caps. | FHP p.9 §4.1 |
| Optimization | In-environment GRPO | 172 machine-built instances; reward = 0.6 rubric + 0.4 judge. | FHP p.12 §6.2 |
| Diagnostics | Coverage suite | 11 tasks × N=3 × 3 backbones, a dual-LLM judge panel, and rule-scored routing and computation rates. | FHP p.19-20 App. B |

### 3. What the evidence actually shows

**Headline results**
- **Main score.** FinanceHarness on Qwen3.6-27B scores 32.4 overall, 45.7 pre-cutoff and 11.8 post-cutoff (SE 0.8). That beats TTD-DR (31.5, SE 0.7) and trails Claude-Opus-4.7 (34.1) and Gemini-3.1-Pro (33.2) in a 30-step ReAct wrapper (FHP p.12 Table 2).
- **Fixed-backbone ablation.** Vanilla 25.3, then Naive harness 29.6, then Harness 32.4, then +GRPO 32.8 (FHP p.13 Table 4).
- **Backbone matters more than scaffold.** At a fixed ReAct wrapper, backbones range from 18.7 to 34.1. At a fixed Gemini-3-Flash, scaffolds range from 27.4 to 31.5 around ReAct's 30.2, and 3 of 5 engineered scaffolds score below plain ReAct (FHP p.11 §6.1, p.12 Table 2).
- **Fine-tuned deep-research models trail general backbones** (21.2–28.2) on the corpus retriever. The authors blame tool-distribution shift and answer-style prose that the "fully grounded" anchor penalizes (FHP p.20 C.1).
- **Only one component was ablated.** Turning URL pre-fetch off raises the visit error rate from 2.1% to 39.4%. The score is said to barely move and cost to rise, but neither is given as a number. Search caps are said to control cost, not quality (FHP p.9 §4.1).
- **Coverage suite.** Coherence and completeness saturate at 4.68 or higher for every backbone; faithfulness (3.85–4.36) and grounding (3.97–4.47) separate them. Routing is 95.8%, golden computation 90.9%, skill hit rate 0.94. Relative valuation is weakest at 3.25/3.33 (FHP p.19-20 Tables 9-10).

**What the ablations say about where gains come from** (my arithmetic on Tables 2 and 4)
- **The score is mostly retrieval by construction.** Overall is about 0.6 × pre + 0.4 × post in every row: (32.4−11.8)/(45.7−11.8) = 0.61, and Opus-4.7 gives 0.60. So roughly 60% of rubric points test retrieval. The paper does not state this.
- **The harness gain is mostly retrieval.** Vanilla to Harness adds +9.6 pre-cutoff and +3.1 post-cutoff. Weighted, about 5.9 of the 7.1-point gain comes from pre-cutoff items. In relative terms, post-cutoff rose more (+36% vs +27%), but from a tiny base.
- **Retrieval skill barely predicts anticipation skill.** Across the 16 non-degenerate systems in Table 2 (excluding gpt-oss-120b and MiroThinker), pre- and post-cutoff scores correlate at r ≈ 0.41 (0.62 with all 18). GPT-5.5 is second on pre-cutoff (47.5) but scores 8.0 post-cutoff. FinanceHarness is not the best on post-cutoff: Gemini-3.1-Pro gets 12.8 and GPT-Researcher 12.0.
- **Per-cell results are uniform but noisy.** Gains are +5.7 to +8.7 in every topic, sector, reasoning-type and situation cell. The hardest cells stay hardest: crypto 24.0, macro and rates 26.9, institutional flows 25.9, performance divergence 27.2 (FHP p.18-19 Tables 5-8). None of these tables has SEs.
- **GRPO adds nothing measurable.** Its +0.4 is below one SE (FHP p.12-13).

**Validity threats** (roughly most to least serious)
1. **Parametric leakage is never tested.** Cutoffs run from Dec 2024 to Nov 2025 (FHP p.8 Fig 4), while the backbones are 2026-era. PIT filtering covers only retrieval.
2. **The released data tools may leak.** They call live yfinance with no as-of parameter, and the prompt injects the real current date (see §6). The paper does not say whether these tools were enabled in FinanceGym runs.
3. **The harness gain cannot be attributed to parts.** "Naive harness" is never defined, and apart from pre-fetch no component is ablated. The +7.1 therefore cannot be assigned to tiers, skills, the grounding review or recovery.
4. **Statistical support is thin.** Each system ran once with sampling temperature 0.6–0.7 in the code profiles. SEs cover resampling of questions only, and there are no paired tests. FinanceHarness vs TTD-DR, and the GRPO gain, are within noise.
5. **The judge is unvalidated.** There is one LLM judge with no judge–human agreement study, and it comes from the same model family as the graph extractor (FHP p.5 §3.2). Its top anchor rewards attribution style (FHP p.20 C.1).
6. **The rubric measures recall only.** "Mentioned" earns credit, and there is no penalty for a confident wrong call and no calibration term (FHP p.7 §3.3). A report that lists many outcomes can score.
7. **The paper contradicts itself in places.**
   - Scores "below 45%" (p.1) against "below 40%" (FHP p.2 §1, p.14 §7), while the Opus-5 run reaches 44.9 (FHP p.11 Fig 5).
   - "23 baselines" (FHP p.10 §6) against 18 rows in Table 2 (FHP p.12).
   - Cutoffs are called "balanced" across months (FHP p.6 §3.2), but Fig 4 shows 3 to 66 questions per month (FHP p.8).
8. **Results with stronger backbones exist only as figure points**, with no table, no SE, no pre/post split and an undisclosed cost method (FHP p.11 Fig 5).
9. **The pre-cutoff tier is easy by construction.** Questions are generated from the same corpus the agent searches, so pre-cutoff facts are findable by design.
10. **The forecast horizon is short.** Reading the right panel of Fig 4, post-cutoff evidence sits mostly within about 1–3 months of the cutoff (FHP p.8 Fig 4). DRF's multi-month and multi-year horizons are a different regime.
11. **The case studies are live-web and unverified** (FHP p.23 App. D) and contain visible errors: a TSLA window forced to a 5-year preset (FHP p.33 App. D.3), and TSM comps listing ASML at an EV/EBITDA of 2618 and giving TSM a +3840% median-implied upside (FHP p.43 App. E.1).
12. **Nothing can be reproduced externally.** The corpus and rubrics are private and grading goes through a leaderboard (FHP p.7 §3.2).

### 4. Mechanisms worth transplanting to DRF (ranked)

The ranking puts evaluation validity first, because every later DRF A/B depends on it. Then come measurement instruments, then cheap deterministic guards, then retrieval and runtime tweaks. It departs from the candidate value scores in one place: P18 (value 2) ranks fourth because it is FHP's central idea and is what makes P07 informative.

| Rank | PID | Mechanism | FHP evidence strength | DRF status | Builds on | Value |
|---|---|---|---|---|---|---|
| 1 | P01 | PIT evidence gates for golden and backtest runs | Premise of the benchmark, unmeasured | absent | C08, C18, C35 | 3 |
| 2 | P17 | Golden set v2 (curation funnel, recomputable resolutions) | Funnel yields only | partial | new | 3 |
| 3 | P07 | Per-model stage and channel value-add arms, frozen retrieval | Backbone > scaffold; single runs | partial | C30 | 3 |
| 4 | P18 | Two-tier rubric and hardened judge | Pre ≫ post in 18/18 systems | partial | new | 2 |
| 5 | P13 | Numeric plausibility and reference-band guards | One concrete tool failure | partial | C07, C24, C48 | 3 |
| 6 | P20 | Cost–quality frontier | Figure only; cost method undisclosed | partial | new | 3 |
| 7 | P22 | Stage-level coverage suite | Descriptive rates | partial | new | 3 |
| 8 | P25 | Grounding finalization and a reports-vs-projects lint | Bundled in the +2.8 step | partial | C33, C32, C27 | 3 |
| 9 | P24 | Search pre-flight; caps treated as cost backstops | One number (2.1% → 39.4%) | partial | C17 | 2 |
| 10 | P29 | Error-classified recovery with cache-safe compaction | None quantitative | partial | C15, C28, C34 | 2 |
| 11 | P31 | Scoping that records default assumptions against as_of | One capability check | partial | C02 | 2 |
| 12 | P27 | Graph situation mining for binaries, with a per-actor budget | Situation types differ in difficulty; unablated | partial | new | 2 |
| 13 | P30 | Constant registry, deferred catalog, numeric recipe skill | Coverage 0.99 / 0.94, descriptive | partial | C45 | 2 |

**1. P01: PIT evidence gates** (FHP p.4-5 §3.1, p.7 §3.3; extends C08, C18, C35)

*What DRF does today*
- **The v3 plan's as_of is wall-clock time.** `as_of = _utc_date()` (`deerflow_bridge/linear_research.py:4212-4216`, `deerflow_bridge/linear_research.py:533-534`).
- **Sources carry no date.** Every row in sources.json gets `"date": None` (`deerflow_bridge/linear_research.py:5580-5591`).
- **Search cannot filter by date.** The agent's search tool takes only a query (`deerflow_bridge/research_gateway.py:3310-3343`), and `deerflow_bridge/search_tools.py` has no match for `date|published|time_range`.
- **The as_of anchor moves the wrong way.** `_validate_as_of_date` moves the anchor forward to the newest source date when a source postdates it, which is the opposite of PIT (`backend/app/services/pipeline_orchestrator.py:10795-10837`).
- **Graphiti's as_of filters on event time, not availability.** It uses `valid_at`/`invalid_at` (`backend/app/services/graphiti_client/runtime.py:1270-1292`).
- **The dateline signal is thrown away.** `_DATELINE_RE` strips "Updated <date>" lines as page chrome (`deerflow_bridge/linear_research.py:2761-2776`), which is exactly the signal PIT needs.
- **Polymarket anchors are live.** They drop closed markets but carry the current price (`deerflow_bridge/market_tools.py:183-210`). The history helper looks back N days from now rather than looking up a price at a given date (`deerflow_bridge/deerflow_research.py:14940-14975`).

*Proposed change*
- **One default-off flag** (for example `RESEARCH_PIT_AS_OF=YYYY-MM-DD`) that golden_eval and backtest runs set, and that the plan persists so resume-by-artifact keeps it (`deerflow_bridge/linear_research.py:4205-4210` reuses the saved plan).
- **In PIT mode:**
  - `plan.as_of` and every prompt's "today" become the flag value.
  - Capture the publication or update date at fetch time, before chrome stripping. Treat undated pages and pages dated on or after as_of as unread and uncitable.
  - Over-fetch search results and drop late ones before fetching. Key `cached_fetch` by PIT mode so a live cached page is never served.
  - Derived artifacts (timeline rows, quantitative_facts, actors claims, graph episodes) inherit the latest availability of the sources behind them.
  - Look up the Polymarket price at as_of, or withhold the anchor.
  - `_validate_as_of_date` drops late sources instead of moving the anchor.
- **Leak handling follows FHP's rule: invalidate, don't penalize.**
  - Write a `pit_audit.json`.
  - Any violation marks the run invalid, and its forecasts never enter the evaluation ledger (the ledger is already isolated: `backend/app/services/forecast_ledger.py:36-62`).
- **This is an integrity requirement, not a measured gain.** It does not touch parametric leakage, so it only pays off together with P17.

**2. P17: Golden set v2** (FHP p.5-6 §3.2, p.9 §5.1)

*The current set*
- **Small and skewed.** 30 questions, 24 YES and 6 NO, 11 of them elections (my count from the file). The schema has 8 fields and no resolution evidence (`backend/tests/eval/golden_questions.json:2-7`).
- **Answerable from memory.** It includes items such as the 2024 US presidential election with an as_of of 2024-11-01 (`backend/tests/eval/golden_questions.json:10-17`).
- **A trivial baseline scores well.** A constant p=0.8 forecaster scores Brier 0.16 on this set (my arithmetic). That is the baseline any pipeline must beat, and memory alone can beat it.

*Proposed changes*
- **Recomputable resolutions.** Add `resolve_time`, `resolution_evidence` (URL, archived snapshot, raw value) and outcome polarity.
- **Numeric-threshold handling.** For numeric thresholds, store the raw series and exclude outcomes that fall within a dead-band of the threshold from Brier and recalibration.
- **FHP's funnel, scaled down:**
  - Stratify by category × difficulty × as_of month × polarity. Greedy stratification is enough at this size; an ILP is not needed.
  - Check each criterion for feasibility: was it knowable from public sources before as_of?
  - Keep a private held-out slice that tuning never sees.
- **Question sourcing.**
  - Prioritize questions that resolve after the serving backbones' training cutoffs.
  - Mine candidates from resolved Polymarket markets and saved dossiers, with human approval; 18% of FHP's expert-reviewed questions failed (FHP p.6 §3.2).
  - Report DRF's own prospective ledger (resolution_autorun) separately, as the only fully leak-free benchmark.

**3. P07: Value-add arms with frozen retrieval** (FHP p.10 §5.2, p.11 §6.1, p.13 Table 4; extends C30)

*What DRF has.* `backend/scripts/model_comparison.py:1-9` already holds research, graph and sim fixed and reruns REPORT per provider. It scores agreement between providers, not accuracy against outcomes.

*Proposed change*
- **The arms.** On the post-cutoff slice of golden v2, and separately for each serving model, run:
  - a compute-matched closed-book prompt;
  - research only;
  - research + graph;
  - research + graph + sim;
  - the full pipeline with market anchoring.
- **Frozen retrieval.** Replay a frozen search and `cached_fetch` snapshot so web drift cannot confound model or prompt effects.
- **Noise floor.** Run at least 3 seeds per arm plus an A/A duplicate to measure it.
- **Adoption rule.** A stage or context block becomes default-on for a model only if its paired bootstrap ΔBrier clears the floor.
- **Why it matters.** This is the per-component ablation FHP lacks. It is the only direct test of whether DRF's simulation earns its cost.

**4. P18: Two-tier rubric and hardened judge** (FHP p.5 §3.2, p.7 Eq.2, p.10 §5.3, p.20 C.1)

*What DRF has.* `backend/scripts/eval_forecast_quality.py:49-56` scores five generic 0–5 dimensions (k=3) with a fixed 0.5 tolerance. `golden_eval` scores only outcome metrics: Brier, log score, ECE and resolution accuracy (`backend/scripts/golden_eval.py:1-42`).

*Proposed change*
- **Two item tiers per golden v2 question:**
  - **Pre-as_of items** test RESEARCH: facts the dossier and actors.json should contain. Many can be scored deterministically, for example by checking that a matching fact is present with a VERIFIED tag.
  - **Post-as_of items** test RUN and REPORT: developments the scenarios and binaries should have anticipated.
- **Scoring.** Anchored 0–4 levels, normalized per question as in Eq.2.
- **Judge hygiene.** The judge sees the resolution evidence, comes from a different model family than the generator, and is checked against a small human-graded set.
- **Gating.** Gate on bootstrap SE rather than a fixed tolerance, and hold report format constant across compared arms so attribution style does not drive the score.
- **Brier, log score and ECE stay primary**, because this rubric cannot penalize miscalibration.

**5. P13: Numeric plausibility and reference-band guards** (FHP p.43 App. E.1, p.19 App. B; extends C07, C24, C48)

*What DRF has*
- **Number verification checks presence only.** It confirms a number appears on the cited page, not that the number is plausible (`deerflow_bridge/linear_research.py:2676-2730`).
- **Report lint's only numeric cross-check** compares scenario percentages in the prose against the spine (`backend/app/services/report_lint.py:781-809`).

*Proposed change*
- **Deterministic validators** on binary thresholds, numeric forecasts and derived figures:
  - unit and currency must match the latest VERIFIED actual in quantitative_facts (`value_type` is typed at `deerflow_bridge/linear_research.py:471-479` and `deerflow_bridge/linear_research.py:6092-6094`);
  - intervals must be ordered;
  - ratios and multiples must fall within ranges;
  - implied changes against the latest actual are capped.
- **Fail closed.** A figure that fails goes to UNVERIFIED or NEEDS_REVIEW, never straight to publication.
- **Simulation numbers stay directional signals.**
- **Evidence.** FHP's own comps tool published an EV/EBITDA of 2,618 and a +3,840% upside with no check. The guard is cheap and deterministic.

**6. P20: Cost–quality frontier** (FHP p.11 Fig 5)

*What DRF has.* Telemetry already exists: `LLMMeter` with `cost_usd` (`backend/app/utils/telemetry.py:223-249`), and the research `UsageLedger` emits one `[usage]` line per response (`deerflow_bridge/research_gateway.py:965-970`, `deerflow_bridge/research_gateway.py:1402-1406`). `golden_eval.py` records no cost or token fields.

*Proposed change*
- Join full-pipeline dollars and tokens per question, covering research, graph, sim and report, into golden and ensemble reports.
- Plot Brier skill against dollars, report ΔBrier skill per 1k tokens against the closed-book arm, and choose defaults from the frontier.
- Avoid FHP's gap: disclose the cost method, and never count only the final call.

**7. P22: Stage coverage suite** (FHP p.19-20 App. B)

*Proposed suite*
- **A fixed set of about 10 tasks**, run on each release and each backbone at N=3.
- **Deterministic rates:**
  - Polymarket anchor matched;
  - actors extracted vs expected;
  - VERIFIED / UNVERIFIED share;
  - share of dated sources (after P01);
  - at least 10 binaries passing the scorecard;
  - spine probabilities summing to 100;
  - lint issue count;
  - sim organic ratio.
- **Optional judge panel.** Two model families, scoring faithfulness and grounding only; FHP found coherence and completeness saturate.
- **Purpose.** Localize regressions without full golden reruns. There is no evidence these rates predict forecast quality.

**8. P25: Grounding finalization and a reports-vs-projects lint** (FHP p.9 §4.1; extends C33, C32, C27)

*Proposed change*
- **Lint rule.** A prose number that matches a quantitative_fact with `value_type` estimate, forecast or target must be marked as a projection or attributed to its source. This mirrors FinanceHarness's "reports vs projects" grounding rule (FinanceHarness `FinanceHarness-0.1.0/financeharness/runtime/prompts.py:62-83`).
- **Guarded attribute-or-soften pass.** Run it on narrative only, and keep a rewrite only if every probability, binary value and VERIFIED number is byte-identical before and after.
- **Validate it separately.** In FHP this pass is bundled into the Naive-to-Harness step, so its own effect is unknown.

**9. P24: Search pre-flight; caps as backstops** (FHP p.9 §4.1; extends C17)

*What DRF has*
- **Search results are rendered directly**, with no liveness check (`deerflow_bridge/research_gateway.py:3544-3582`).
- **The 200-character dead-fetch floor** applies only after the agent chooses to fetch (`deerflow_bridge/cached_fetch.py:50-56`, `deerflow_bridge/cached_fetch.py:600-608`).

*Proposed change*
- **Flag-gated pre-flight:**
  - over-fetch 2×;
  - make bounded, concurrent, single-attempt direct GETs into `cached_fetch`;
  - drop walls and dead pages;
  - fall back to unvalidated rows, labelled as such.
- **Budget accounting.** Pre-flight must count against the fetch caps (`deerflow_bridge/research_budget.py:30-36`, `deerflow_bridge/research_budget.py:296-304`) or have its own cap.
- **Measurement.** Measure tokens per KIQ and wasted fetch turns, not Brier.
- **Fit with P01.** This is also where the PIT date filter naturally sits.
- **Caps stay anti-runaway backstops.**

**10. P29: Error-classified recovery** (FHP p.8-9 §4.1; extends C15, C28, C34)

*What DRF has*
- **Seven error classes** in `deerflow_bridge/research_gateway.py:314-352`.
- **Only transient and unknown errors retry.** A `bad_request` is terminal except for the GLM parameter-degrade ladder (`deerflow_bridge/research_gateway.py:1700-1733`, `deerflow_bridge/research_gateway.py:1785-1795`).
- **Empty content with `finish_reason=length` raises** (`backend/app/utils/llm_client.py:929-938`).

*Proposed change*
- Re-roll a malformed-generation 400 at most twice, following FinanceHarness's REGENERATE class.
- Escalate `max_tokens` within a bound on truncation.
- Compact only at KIQ boundaries so prompt caching survives, and keep full tool output on disk.

**11. P31: Scoping assumptions against as_of** (FHP p.19 App. B; extends C02)

*What DRF has*
- **v3 SCOPE already restates the question and horizon** from a brief that carries As-of (`deerflow_bridge/linear_research.py:388-399`).
- **But as_of is wall-clock time** (see P01).
- **`requirement_spec` is only a format contract** (`backend/app/services/requirement_spec.py:1-10`).

*Proposed change*
- Add at most 3 `assumptions` to SCOPE: units or currency, resolution source, entity disambiguation, period convention.
- Persist them in plan.json and feed them to the spine's resolution_criteria, binary extraction and the resolution monitor.
- Anchor relative dates to `plan.as_of`. The system never asks the user a question.

**12. P27: Situation mining for binaries** (FHP p.5 §3.2, p.19 Table 8)

*What DRF has*
- **contested_claims already exist** (`deerflow_bridge/linear_research.py:471-479`) and are injected as a bullet list into the prompts of risk and uncertainty sections (`backend/app/services/report_agent.py:2075-2102`).
- **But they are not an input to binary extraction** (`backend/app/services/forecast_extractor.py:2621-2630`).
- **Graph primitives already exist:** causal paths and N-hop subgraphs with `as_of` (`backend/app/services/graphiti_client/runtime.py:1294-1300`, `backend/app/services/graphiti_client/runtime.py:1383-1386`) and degree centrality (`backend/app/mcp/kg_server.py:181-211`).

*Proposed change*
- Pass contested claims, the top-centrality actors and 2–3-hop driver chains to binary extraction as candidate propositions.
- Cap binaries per primary actor (for example 3 of 10 or more).
- This uses deterministic queries and adds no LLM calls. The evidence for it is weak.

**13. P30: Constant registry, deferred catalog, numeric recipe** (FHP p.8-9 §4.1; extends C45)

*What DRF has.* v3 binds one constant two-tool schema for cache discipline (`deerflow_bridge/research_gateway.py:15-20`, `deerflow_bridge/research_gateway.py:3310-3343`).

*Proposed change.* Only once calc, market-history or data tools are added:
- deliver deferred schemas as append-only tool results through a fixed dispatcher;
- add a numeric-forecast recipe: latest verified actual, then trend or base rate via calc, then the market anchor, then an interval with its assumptions.

The value is low today.

### 5. What not to transplant, and why

- **GRPO / in-environment RL** (FHP p.12-13 §6.2). DRF does not train models, and the +0.4 gain is below one SE.
- **The 0–4 recall rubric as a primary metric or sole gate** (FHP p.7 §3.3). It gives credit for hedged listing of outcomes and never penalizes confident wrong calls. Use it only as the P18 diagnostic.
- **Porting the open-ended ReAct-style harness wholesale.** Its gain is mostly retrieval, which v3 already covers with verification. FHP's own data show that 3 of 5 engineered scaffolds lose to plain ReAct (FHP p.11-12 §6.1).
- **A `load_tool` that changes the visible tool list mid-conversation, or compaction by elision at arbitrary turns.** Both break byte-identical prompt prefixes, which v3's cache discipline depends on (`deerflow_bridge/research_gateway.py:15-20`).
- **An unconditional self-review rewrite of the whole report.** The same model checks its own claims, and nothing verifies that figures survive the rewrite. In DRF it could silently change probabilities.
- **Live data or valuation tools without as_of** (yfinance-style DCF, WACC, comps). They leak post-cutoff data, show a demonstrated failure mode (FHP p.43 App. E.1), and are off-domain for DRF's questions.
- **Interactive clarification questions.** DRF runs unattended; take only the recorded assumptions (P31).
- **Eq.1 cutoff scoring and ILP balancing.** There is no evidence either helps (FHP p.5-6 §3.2), and a 30–100-question set only needs stratified sampling.
- **A private-rubric leaderboard.** DRF must be reproducible locally; a private held-out slice is enough.
- **Generating golden questions from the same cache or corpus the run searches.** The pre-cutoff tier then becomes findable by construction.
- **FinanceHarness's bibliography retrofit**, which appends every visited page including uncited ones (FinanceHarness `FinanceHarness-0.1.0/financeharness/runtime/citations.py:42-95`). DRF already lists cited sources only (`deerflow_bridge/linear_research.py:5580-5591`).
- **Adopting fine-tuned deep-research models trained on other tool stacks** (FHP p.20 C.1).

### 6. Paper vs code

The release contains the harness runtime only. Where it overlaps with §4.1 of the paper it is faithful. None of the apparatus behind Tables 2–10 is included.

| Paper claim | FinanceHarness-0.1.0 (paths under `financeharness/` unless noted) | Verdict |
|---|---|---|
| PIT FAISS sandbox with cutoff filtering (FHP p.4-5 §3.1) | The default search backend is DuckDuckGo via `ddgs`; a corpus index "can be added later" (`FinanceHarness-0.1.0/financeharness/tools/research/search_backends.py:1-6`). No match in the source code for `cutoff`, `as_of`, `pub_date`, `faiss` or `htmldate` (`htmldate` appears only as a transitive entry in `uv.lock`). | Absent |
| Agent receives question plus cutoff (FHP p.10 §5.3) | The prompt injects the real `datetime.date.today()` (`FinanceHarness-0.1.0/financeharness/runtime/prompts.py:183-197`). `run_research` has no cutoff parameter (`FinanceHarness-0.1.0/financeharness/research.py:24-40`). | Diverges |
| Data tools (not specified for FinanceGym runs) | Live yfinance with preset periods only (`FinanceHarness-0.1.0/financeharness/tools/data/equity/prices.py:20`, `:159`), which matches the TSLA caveat (FHP p.33 App. D.3). | Leakage risk, undisclosed |
| Benchmark builder, judge, Eq.1/Eq.2, ILP, GRPO reward | No code; the README points to google-research. No match for `grpo`, `reward` or `rubric`. | Absent |
| Vanilla / Naive / 30-step ReAct configurations (FHP p.13 Table 4; FHP p.10 §5.2) | Not shipped. | Table 4 not reproducible |
| Bounded runtime and budgets (FHP p.8-9 §4.1) | `max_rounds` 100, 3600 s wall clock, 1800 s per call, described as "anti-runaway backstops, not a quality budget" (`configs/runtime.json`; `FinanceHarness-0.1.0/financeharness/runtime/agent.py:326-336`). No search-budget cap exists. | Loop matches; caps absent |
| Tool tiers and MCP/CLI extension tier (FHP p.8 §4.1) | 7 core and 14 deferred tools with a sorted catalog (`FinanceHarness-0.1.0/financeharness/runtime/tool_registry.py:145-153`). No MCP code. | Tiers match; extension tier absent |
| Modes over a constant registry; skills (FHP p.8-9 §4.1) | Matches (`FinanceHarness-0.1.0/financeharness/research.py:52-58`). 5 skills are bundled; `industry-analysis`, used at FHP p.42 App. E.1, is missing. | Mostly matches |
| Citation retrofit (FHP p.9 §4.1) | The finalizer strips model-written references and orphan markers, then appends every visited page (`FinanceHarness-0.1.0/financeharness/runtime/citations.py:42-95`). It never inserts inline markers. | Weaker than implied |
| Grounding review (FHP p.9 §4.1) | One re-decode with no tools (`FinanceHarness-0.1.0/financeharness/runtime/agent.py:246-271`), on by default only in research mode (`FinanceHarness-0.1.0/financeharness/research.py:84-92`). The paper does not mention the mode gating. | Partial match |
| URL pre-fetch "validates document IDs" (FHP p.9 §4.1) | Search-result pre-flight on live URLs: 2× over-fetch, at most 16 checks, concurrency 8, 200-character floor, cache warm-up, fallback to unvalidated results (`FinanceHarness-0.1.0/financeharness/tools/research/search.py:27-35`, `:139-147`). The 2.1% → 39.4% figure cannot be checked from the repo. | Different mechanism |
| Recovery (FHP p.8-9 §4.1) | Four classes, COMPACT / REGENERATE / BACKOFF / FATAL (`FinanceHarness-0.1.0/financeharness/runtime/recovery.py:20-23`, `:67-72`). `max_tokens` escalates from 16,384 to 65,536 (`configs/runtime.json`). | Matches |
| Backbones: Qwen3.6-27B, Gemini-3.5-Flash, GPT-5.5 | Default is gemini-3.6-flash; also gpt-5.6, and qwen36-27b-fp8 at temperature 0.6 (`FinanceHarness-0.1.0/financeharness/providers/profiles.py:87-130`). | Newer / quantized |
| Design evidence the paper omits | About 89% of visit failures were malformed multi-URL arguments (`FinanceHarness-0.1.0/financeharness/tools/research/visit.py:59-64`). | Code-only insight |
| Comps output (FHP p.43 App. E.1) | Peer medians with no outlier, currency or unit guard (`FinanceHarness-0.1.0/financeharness/tools/data/equity/comps.py:163-190`). | Explains the 2618× failure |
| Clarification capability (FHP p.19 App. B) | JSON with `sufficient`, at most 3 `assumptions`, fails open (`FinanceHarness-0.1.0/financeharness/clarify.py:38-57`; fail-open handlers `FinanceHarness-0.1.0/financeharness/clarify.py:108-109`, `FinanceHarness-0.1.0/financeharness/clarify.py:152-153`). | Matches |

## StockAgent (paper)

*Zhang, Liu, Zhang et al., "When AI Meets Finance (StockAgent)", arXiv 2407.18957v5, June 2026 (SAP p.1). The released code is at `/Users/rogerlin/Downloads/finharness/Stockagent-main` and is cited here as `Stockagent-main/<file>:<lines>`. DRF anchors are relative to the DRF repo root.*

### 1. Essence

StockAgent puts a population of LLM traders into a closed market. The market has an order book, a public tip board, credit, and scheduled macro and earnings shocks. The authors ask whether such a market can show how outside information shapes trading, and they rename the real stocks "A" and "B" to keep the model's memorised price history out of play (SAP p.1 Abstract; p.5-6 §3; p.6 §4; p.8 §4.2.1, §4.3).

The simulator itself is a toy (two stocks, exact-price matching), and every condition was run once. Even so, two lessons matter for DRF:

- **The backbone model decides the outcome.** The paper's only large, clear result comes from swapping the backbone under identical inputs, and the swap reversed the market. GPT-3.5 pushed Stock A from about 35 to above 100 in ten days. Gemini-pro pushed it from about 30 to about 19. The two price paths correlate at r = -0.86, and GPT traded 24 times as many A shares (SAP p.14 Fig.4; p.15 Table 10). The authors conclude that in-context information did not override each backbone's built-in disposition (SAP p.21 §6.2). That is a direct threat to treating a single-backbone LLM simulation as forecast evidence, which is exactly what DRF's RUN stage produces.
- **Its channel ablation (RQ3) shows what not to do.** It has no full-information control and no seeds. It contains duplicated data series. The ablation that should have done nothing mechanically produced the largest effect. Read in reverse, it lists the controls DRF needs before simulation output may ever move a published probability.

A smaller third idea is the "secretary": a deterministic validator that checks every LLM decision for feasibility and sends the specific error back for a retry (SAP p.5 §3.1; p.24-25 App. A.1; `Stockagent-main/secretary.py:36-181`).

### 2. Method at a glance

| Component | Mechanism | Anchor |
|---|---|---|
| Investment agents | 200 LLM traders (50 in the code). Random assets from 100k to 5M, debt no larger than assets, one of 4 personality labels | SAP p.5 §3.1; p.7 §4.1.2; p.14 Table 9; `Stockagent-main/util.py:161` |
| Secretary | Checks format, then schema, then feasibility (cash, holdings, loan cap). Echoes the error and retries up to 3 times, then defaults to "do nothing" | SAP p.5 §3.1; p.24-25 App. A.1; `Stockagent-main/secretary.py:36-181`; `Stockagent-main/agent.py:271-286` |
| Transaction module | One dictionary order book per stock. A fill happens only when bid equals ask; partial fills allowed | SAP p.5 §3.2; p.8 §4.2.2 |
| Price formation | Price becomes the last trade of each session; unchanged if nothing traded | SAP p.8 §4.2.2; `Stockagent-main/stock.py:21-26` |
| Activation order | A new random permutation each session ("random clock page replacement") | SAP p.5 §3.2 Fig.1; p.8 §4.2.2 |
| BBS (bulletin board) | Every agent posts a tip after the close; all posts are shown to everyone the next day | SAP p.6 §3.3; p.8 §4.2.3 |
| Day loop | Before trading: interest, repayment, bankruptcy, events/reports, loan decision. Then 3 sessions. After trading: next-day intent and a BBS post. 4 kinds of LLM call per day | SAP p.7 Fig.2; p.7-8 §4.2 |
| Market settings | 264 days in 66-day quarters; 1-, 2- and 3-month loans at 2.7%, 3.0% and 3.3%; fee 0.005 per share (min 1, max 5.95) | SAP p.7 §4.1.2-4.1.3 |
| Exogenous events | Reports on days 12, 78, 144 and 210; easing, a rate hike and guidance surprises modelled on 2014-2019 | SAP p.8 §4.2.1, §4.3; p.9 Table 1 |
| Valuation anchor | FCFF/WACC/CAPM price bands (base, upper, lower) at each disclosure date | SAP p.9 §4.4 Eq.1-6; p.10-12 Tables 2-7 |
| Leakage control | Real US company statements, renamed Stock A and Stock B, with generic backstories | SAP p.1 Abstract; p.6 §4; p.25-26 App. A.2 |
| Experiments | RQ1/RQ2: GPT-3.5-turbo-0125 vs Gemini-pro-1.0, 10 days. RQ3: Gemini with 5 leave-one-channel-out conditions over 30 rounds | SAP p.12 §5.1; p.13-14 §5.2 Table 9; p.16 §5.5 |

**Cost, from the code (the paper reports none):** each agent makes 6 LLM calls per day plus retries (5 once its loan cap is used up, `Stockagent-main/agent.py:186-187`). A 200-agent, 10-day run therefore needs about 12,000 calls, and all 200 posts are re-injected every day (`Stockagent-main/main.py:139-189`).

### 3. What the evidence actually shows

**Backbone swap (RQ1/RQ2): one run per model**

| Measure | GPT-3.5 | Gemini-pro | Anchor |
|---|---|---|---|
| Stock A path over 10 days (read from plot) | about 35 to above 100 | about 30 to about 19 | SAP p.14 Fig.4 |
| r(A, B) within the same backbone | 0.94 | 0.11 | SAP p.14 Fig.4 |
| r(GPT_A, Gemini_A) | -0.86 (shared) | | SAP p.14 Fig.4 |
| A shares traded | 3,118,792 | 128,981 (GPT about 24x) | SAP p.15 Table 10 |
| A dollar volume | 176.8M | 3.59M (GPT about 49x) | SAP p.15 Table 10 |
| A trade count | 384 | 800 | SAP p.15 Table 11 |
| Average A trade size (my derivation) | about 8,100 shares | about 161 shares | Tables 10-11 |
| A VWAP (my derivation) | 56.7 | 27.8 | Table 10 |
| Table 11 "Stock A price" (statistic not defined) | 55.70 | 23.46 | Compare the D1 fundamental band 26.24-27.33 (SAP p.11 Table 6) |
| Agent clustering | Dispersed | Homogeneous (herding) | SAP p.15 Fig.5; p.16 §5.3.3 (qualitative) |

**Channel ablation (RQ3, Gemini, 30 rounds, one run each, no full-information control).** Price paths are from SAP p.32-33 Tables 17-18. I recomputed the per-agent P&L statistics from SAP p.27-31 Tables 12-16.

| Condition | Stock A, round 1 to 30 | Stock B, round 1 to 30 | P&L across 200 agents: mean / SD / number profitable |
|---|---|---|---|
| No financial information | 29.0 to 25.3 (-12.8%) | 39.0 to 33.4 (-14.4%) | -240k / 1.60M / 111 |
| No BBS | 28.0 to 26.4 (-5.7%) | 39.1 to 37.8 (-3.3%) | -9.1k / 36.7k / 100 |
| No statements | 30.2 to 28.0 (-7.3%) | 44.4 to 33.1 (-25.5%); one step from 42.0 to 33.0 at round 23 | +0.7k / 78k / 99 |
| No later loans | 29.0 to 26.4 (-9.0%) | Identical to No BBS in all 30 rounds | +383k / 286k / 194 |
| No interest change | 30.0 to 62.5 (+108%) | 40.0 to 46.0 (+15%) | Not tabulated; plotted in Fig.10 only |

A trade counts read from the Fig.9 bars are about 205, 242, 257, 209 and 305 (SAP p.18 Fig.9). The condition labels in Fig.9 do not match the table names, so mapping these counts to conditions is ambiguous.

**Which components matter, and by how much**

- **Backbone.** This is the only effect that is large compared with anything else measured: the price direction reverses and share volume differs about 24x. It is still n=1 per model on 2024-era models.
- **Channels.** Four of the five ablations drift Stock A down by 3-13%, the same direction as Gemini's bearish RQ1 run. Without a full-information control, channel effects cannot be told apart from the backbone's drift. Only three findings stand out:
  - No interest change: A +108%.
  - No statements: a one-step drop in B at round 23.
  - No financial information: P&L SD of 1.60M, 6 to 44 times the other conditions' 37k-286k. This is the only channel claim the tables clearly support.

**Validity threats**

- **No replication.** Every condition is one stochastic run. There are no seeds, no confidence intervals and no tests, although regression and ANOVA are promised (SAP p.13 §5.2). The code samples at temperature 1.0 and never seeds its shuffle (`Stockagent-main/agent.py:69-73`, `Stockagent-main/main.py:148-150`).
- **No control arm for RQ3.** Every "effect" is a comparison between two ablations.
- **Data integrity.** I verified these against the tables:
  - No_Loan_B equals NoBBS_B in all 30 rounds.
  - No_Loan_A equals NoBBS_A plus 1.0 in rounds 1-8 and is identical in rounds 9-17 and 24-30 (SAP p.32-33 Tables 17-18).
  - Non-statement P&L rows 195-199 repeat earlier rows (SAP p.31).
- **Text contradicts the data:**
  - §5.4 says trends are similar across the two models, but Fig.4 gives r = -0.86 (SAP p.16).
  - Fig.6 shows Gemini's A orders rising from 30 to about 48 (SAP p.17), against Fig.4 and Table 11.
  - The claim that A outperforms B under both models fails for Gemini in Fig.4.
  - The paper calls No later loans "more conservative and bearish" (SAP p.19 §5.5.2), yet 194 of 200 agents profit.
  - The text puts the B crash at round 21; Table 17 shows round 23.
- **The horizon cannot trigger the ablated mechanics.**
  - The text says 10 days (SAP p.16 §5.5), Table 9 says 154 days (SAP p.14), and the market setup says 264 days (SAP p.7 §4.1.3).
  - Under the released schedule the first report is on day 12, events are on days 78 and 144, and interest starts on day 22 (`Stockagent-main/util.py:239-245, 272-281`), so none of them fires in 10 days.
  - If "no interest change" means removing the rate events, it was a no-op, yet it produced the largest effect. If it means 0% loans, it changes the price of credit in the day-1 loan prompt. The paper does not say which.
- **Prompt confounds.** The trade prompt says "Encourage buying and selling as much as you can" (SAP p.24-25 App. A.1). The day-1 background also contains first-person bull and bear opinions (SAP p.25-26). Both could create the "disposition" and volume effects that the paper attributes to the models.
- **Leakage claim never tested.** The paper claims anonymisation prevents leakage (SAP p.1 Abstract; p.21 §7) but runs no probe, even though the statements come from real US firms (SAP p.6 §4).
- **P&L never defined.** A +76.7M aggregate gain while both No-Loan prices fall cannot happen in a closed, fee-free market. Borrowed cash counted as profit, or shares created by the settlement bug (§6), are possible explanations.
- **Weak metrics.** Pearson r on two trending series mostly encodes trend direction. RQ2's "prior knowledge" is never operationalised. There is no stylised-fact or real-path validation, and no cost reporting.

**Bottom line.** Treat SAP as a credible qualitative warning that the backbone can dominate an LLM-agent simulation, and as a checklist of evaluation mistakes. None of its effect sizes should be used quantitatively.

### 4. Mechanisms worth transplanting to DRF (ranked)

DRF already holds the most important defensive position. By default, simulation output cannot move a published probability: `SIMULATION_FORECAST_EFFECT=diagnostic_only`, and `validated_update` stays closed until an outcome-blind promotion (backend/app/config.py:1475-1488; backend/app/services/decision_channel.py:722-749; backend/app/services/forecast_extractor.py:2654-2660).

SAP's lessons therefore land in two places:

- the evidence a simulation must show before any promotion (items 1, 2, 5);
- honesty fixes in the channel that produces WorldState and in the evaluation harness (items 3, 4, 6, 7, 8).

Every item below is proposed behind a flag, defaults off or warning-only, and is deterministic wherever no LLM is needed.

**1. P15: Backbone-sensitivity check (relation: new; value 3; status: partial)**

- **What SAP shows.** The same inputs gave opposite market direction and 24x the share volume under the two backbones (SAP p.14 Fig.4; p.15 Tables 10-11; p.21 §6.2).
- **DRF today.**
  - RUN uses one backbone. The decision channel is a single batched call that assigns every actor's commitment (backend/app/services/decision_channel.py:173-213, 246-255). So the "population" is really one model's opinion, which is SAP's failure mode in its purest form.
  - Cross-model checks exist only at REPORT:
    - model_comparison re-runs REPORT alone on a fixed simulation (backend/scripts/model_comparison.py:4-9).
    - `FORECAST_ENSEMBLE_MODELS` pools binary forecasts across providers (backend/app/services/forecast_extractor.py:2770-2802) but is empty by default (backend/app/config.py:643).
  - When pooling does run, the pooled mean overwrites the probability, and disagreement is only flagged when spread exceeds 0.15 (backend/app/services/ensemble.py:331-344). A 0.3/0.7 split publishes as 0.5, which reads as genuine uncertainty rather than model dependence.
- **Transplant.**
  - **Tier 1 (cheap).** `run_decision_channel` already takes `llm` as an argument and replays the frozen action log (backend/app/services/decision_channel.py:535-565). Replay it with a second provider's per-instance client (backend/scripts/model_comparison.py:24-26). This costs one batched call per round, because the calendar cache keys by period label (backend/app/services/decision_channel.py:631-653). Compare, per round and at the end:
    - the leading scenario;
    - the sign of each scenario's shift from the seed;
    - total-variation distance;
    - Pearson r over valid rounds, only when there are at least 5.
  - **Tier 2 (golden and backtest only).** A full second-provider RUN on the same PREPARE fork.
  - **Binary tier.** When members fall on both sides of 0.5, mark the forecast `model_dependent` and write that to the ledger. Surface model dependence explicitly rather than folding it into the pooled mean.
- **Fail-closed rule.** If the leading scenario or the shift direction flips across backbones, force `forecast_effect=no_update`, record `backbone_disagreement`, and label the WorldState prose as backbone-dependent. Make agreement a precondition for any future `validated_update`.
- **Acceptance check.** A stub provider that reverses assignments flips the verdict and sets `no_update`. Two identical stubs give agreement 1.0. Always run a same-provider A/A pair first, so sampling noise is not mistaken for backbone sensitivity (links to item 2).

**2. P07: Channel ablation with a full-information control and an A/A noise floor (extends C30; value 3)**

- **What SAP shows.** RQ3 (SAP p.16 §5.5; p.18 Figs 8-9; p.27-33 Tables 12-18) is exactly what goes wrong without a control, seeds and a noise floor.
- **DRF today.**
  - No ablation, placebo or noise-floor code exists in services or scripts; a grep for these terms finds nothing.
  - Seed ensembles exist only as N PREPARE-fork runs with `SIM_SEED` (backend/scripts/forecast_tools.py:1-8).
  - Candidate channels that plausibly steer outcomes:
    - the numeric seeded-prior line in the decision prompt (backend/app/services/decision_channel.py:191-198);
    - scheduled events;
    - actor posts and the world delta;
    - the Polymarket block;
    - dossier quantitative facts.
- **Transplant, report layer first (cheap).**
  - Re-derive the spine and binaries with one context block removed and record each binary's probability change.
  - Always run the full-information arm twice (A/A) to measure the noise floor, with at least 3 repeats per arm.
  - Compare arms with a paired bootstrap.
- **Simulation layer (backtest/golden only).** Use decision-channel replay arms:
  - a non-LLM control: argmax of the seeded prior through a deterministic stub LLM (C30a);
  - no prior line;
  - no events;
  - no posts.
- **Verdicts.**
  - A channel "matters" only if its delta exceeds the A/A floor.
  - The simulation is "hollow" if the LLM arm is indistinguishable from the non-LLM control and every channel delta sits inside the floor.
  - Each arm must assert that the removed channel had content in the control (for example, at least one fired event inside the horizon); otherwise the arm is labelled `vacuous`. This is SAP's no-op lesson.
- **Acceptance check.** A synthetic stub in which only events matter shows only the no-events arm above the floor.

**3. P26: Secretary-style feasibility validator that emits INFEASIBLE (extends C10, C26, C31; value 3)**

- **What SAP shows.** Format, schema and feasibility checks, three error-echo retries, then a silent no-op (SAP p.5 §3.1; p.24-25; `Stockagent-main/secretary.py:36-181`; `Stockagent-main/agent.py:271-286`). The paper reports no repair rates. The released loan-retry path could never succeed because it passes the date where the response belongs, so the format check always fails (`Stockagent-main/agent.py:208`), which is a reminder to test the repair path itself.
- **DRF gaps (verified in code).**
  - `chat_json` only repairs syntax and resends once, blindly, at a lower temperature (backend/app/utils/llm_client.py:584-599).
  - Per-decision handling (backend/app/services/decision_channel.py:269-283):
    - silently drops non-candidate scenarios;
    - never checks that `agent_id` is in the roster;
    - never removes duplicate ids;
    - forwards `magnitude` unchecked, although the prompt asks for 0-1 (backend/app/services/decision_channel.py:207-211).
  - WorldState floors magnitude at 0 but never caps it (backend/app/services/worldstate.py:105, 211). Unknown ids receive weight 1.0 (backend/app/services/worldstate.py:111-113).
  - Consequence: one malformed item with magnitude 10 outvotes ten valid commitments, and invented or duplicated ids add weight.
  - `ROUND_STATUS_INFEASIBLE` is reserved but never emitted (backend/app/services/worldstate.py:38, 48). `round_accounting` names only failed and missing rounds (backend/app/services/worldstate.py:245-253).
- **Transplant.**
  - A pure validator `(decisions, roster, scenarios) -> (ok, reasons, normalized)` that rejects:
    - unknown ids;
    - duplicate ids;
    - non-candidate scenarios;
    - magnitude or confidence outside [0,1];
    - with C31, commitments above an actor's capacity.
  - One bounded repair turn that names the offending items and the allowed values.
  - If the reply is still infeasible, set `round_status=infeasible`. WorldState already freezes on statuses outside the valid set (backend/app/services/worldstate.py:195-200).
  - Add an `infeasible_rounds` count and demote run validity the same way failed rounds do.
  - Emit invalid, repair and infeasible rates as telemetry.
- **Cost.** Zero extra calls when the reply is valid.
- **Acceptance check.** One fixture per violation, plus a test that the repair reply is itself re-validated.

**4. P13: Reference-band guard for numeric outputs (extends C07, C24, C48; value 3)**

- **What SAP shows.** Its FCFF bands (SAP p.9 Eq.1-6; p.11-12 Tables 6-7) were never used as a metric. The prices the LLMs formed left the band within days: GPT's VWAP was about 56.7 against a band of 26.24-27.33, and Gemini's Table 11 price of 23.46 sat below it.
- **DRF today.**
  - Simulation numbers are already diagnostic-only.
  - Report numbers get only a prose regex that flags year-on-year growth above 100% (backend/app/services/report_agent.py:4928-4967).
  - report_lint's only numeric-consistency rule checks scenario probabilities against the spine (backend/app/services/report_lint.py:781).
- **Transplant.**
  - Build a deterministic band from dossier quantitative facts, the Polymarket-implied range and C24 tools (for example, a lognormal P(S_T > K) at the question horizon).
  - Add a lint rule: any numeric forecast or threshold outside the band needs a cited justification; otherwise it is marked `unverified`.
  - Numbers that emerge inside the simulation, including any C48 market price, stay directional-only.
- **Evidence.** Anecdotal (one run per model), but the guard is cheap.

**5. P23: Simulation prompt hygiene (extends C42, C16; value 3)**

- **What SAP shows.**
  - In the code, persona, the previous day's posts and event notices reach only the loan prompt. That prompt is skipped when `max_loan <= 0` (`Stockagent-main/agent.py:186-187`), and chat history is wiped daily (`Stockagent-main/main.py:115`), so affected agents miss all three.
  - Events are pushed into the peer forum as if posted by an admin (`Stockagent-main/main.py:131-137`), so removing the forum also removes the events.
  - The activity nudge cited in §3 confounds every volume result.
- **DRF today, mostly good.** The world-clock header is re-rendered every round, sent as a USER message, and carries CONFIRMED EVENTS and WHAT CHANGED (backend/scripts/run_parallel_simulation.py:1940-2020). Tests pin it (backend/tests/test_calendar_round_loop.py:323-332). It also explicitly legitimises doing nothing (backend/scripts/run_parallel_simulation.py:1995), which is the anti-nudge SAP lacked.
- **Remaining gaps.**
  - Scheduled events also enter the social feed as an ordinary post under a matched actor's account. The `is_scheduled_event` marker exists only in the action log, not in the post agents see (backend/scripts/run_parallel_simulation.py:2531-2561). Event provenance is therefore mixed with actor speech, which is SAP's entanglement again.
  - Header injection skips a failing agent silently, with no count (backend/scripts/run_parallel_simulation.py:2012-2020).
  - There is no lint for DRF-authored activity nudges or uncited directional opinions. The existing sanitiser targets injected instructions only (backend/app/services/actor_role_prompt.py:96-119).
- **Transplant.**
  - Post events under a privileged "wire" identity (C42).
  - Count header-delivery failures in the LLM health output.
  - Add a warning-only lint over generated personas and briefs (English and Chinese lexicon), in the same place as the existing sanitiser.
  - Tag each per-period phase as LLM or deterministic.

**6. P21: Output-side simulation health diagnostics (extends C16, C26, C30; value 2)**

- **What SAP shows.** Herding read from t-SNE plots (SAP p.15 Fig.5; p.16 §5.3.3). Event response is never measured.
- **DRF today.**
  - Health is errored, hollow, truncated, llm_degraded or ok, based on organic counts and LLM health (backend/app/services/simulation_runner.py:2125-2146).
  - An organic-ratio collapse detector exists (backend/app/services/agent_dynamics.py:335-349).
  - An input-side herding guard keeps numbers out of the world delta (backend/app/services/world_delta.py:1-12).
  - Nothing checks whether commitments herd or react to events.
  - The roster is sorted by activation (backend/app/services/decision_channel.py:424), so list position equals influence, a position-bias confound (C26 seeded shuffle).
- **Transplant.** Deterministic metrics over decisions and the trajectory:
  - per-round normalised entropy of chosen scenarios;
  - modal-scenario share;
  - pairwise dispersion of (scenario, magnitude, confidence);
  - per-event response: the share change after each fired event against median non-event periods and the A/A floor;
  - order effect: one seeded-permutation replay using the Tier-1 mechanism from item 1.
  Results are written next to `simulation_health` and stay warning-only until thresholds are calibrated on golden runs.

**7. P06: Golden-eval statistical rigour and result integrity (extends C40; value 3)**

- **What SAP shows (as a warning).** n=1 runs, missing tests and duplicated series (§3).
- **DRF today.**
  - golden_eval reports Brier, log score, accuracy, base rate, ECE and category breakdowns (backend/scripts/golden_eval.py:147-182). It tells users to diff `eval_report.json` across versions (backend/scripts/golden_eval.py:19-30).
  - There is no climatology Brier, skill score, confidence interval or paired test.
  - The golden set has 30 questions with 24 resolved YES (backend/tests/eval/golden_questions.json, counted), so a constant 0.8 already scores Brier 0.160.
  - Ensemble agreement has no duplicate-member check (backend/app/services/ensemble.py:150-175, 348-363).
- **Transplant.**
  - Climatology Brier and a Brier skill score.
  - Question-clustered bootstrap confidence intervals.
  - Paired bootstrap ΔBrier between versions.
  - At least 3 repeats per arm, with the spread reported.
  - An integrity lint that hashes each member run's decisions and forecast vector, refuses agreement computed over duplicates, and recomputes headline numbers from per-item rows.

**8. P03: Contamination probes for golden eval (extends C21; value 3)**

- **What SAP contributes.** The masking idea, plus the lesson that the mask must be tested: its anonymisation claim was never probed (SAP p.1 Abstract; p.6 §4).
- **DRF today.**
  - Golden questions are real, named 2024-2025 events (backend/tests/eval/golden_questions.json:8-309).
  - The as-of constraint does not bound what the model has memorised.
  - On the retrieval side, an as_of earlier than the newest source is moved forward to that source's date rather than filtering later sources out (backend/app/services/pipeline_orchestrator.py:10823-10834).
- **Transplant.** Per golden question, run three arms:
  - closed-book;
  - masked: consistent pseudonyms for entities and absolute dates, taken from actors.json;
  - full pipeline.
  Then:
  - run a recognition probe on the masked text;
  - flag and report separately any question where the closed-book arm is confident and correct;
  - add a dispersion check so a probe that collapses to a constant is not read as "clean".
- **Cost.** About twice the evaluation cost.
- **Limit.** This covers memorised knowledge only; retrieval leakage needs date-bounded search, which is outside SAP's scope.

### 5. What not to transplant

- **Order book, exact-price matching, last-trade price** (SAP p.8 §4.2.2). Trades happen only when LLMs quote identical numbers, so prices jump, and they drifted to twice the fundamental band. If DRF ever builds an in-simulation market (C48), it needs LMSR or crossing orders with escrow, and it stays diagnostic-only.
- **Random endowments and 4 generic personality labels** (SAP p.5 §3.1; p.6-7 §4.1.2). DRF's dossier-grounded real actors are strictly better. SAP never shows personas matter, and Gemini agents herded anyway (SAP p.16 §5.3.3).
- **Credit, interest, fee and bankruptcy mechanics** (SAP p.7 §4.1.2-4.2.1; p.8 §4.2.1). These are trading-specific, and the code versions are wrong (§6). Only the idea of a typed capacity that feeds feasibility checks survives, via item 3 and C31.
- **Broadcast-everything forum** (SAP p.6 §3.3). Token cost grows quadratically. DRF's top-k, character-capped world delta (backend/app/services/world_delta.py:21-31) is already the better design.
- **Day-scoped memory with key facts only in a skippable first prompt.** This is an anti-pattern. The lesson transfers (item 5); the mechanism does not.
- **Unseeded shuffle as "deadlock avoidance"** (SAP p.5 §3.2). DRF's batched call has no contention. Only a seeded shuffle to counter position bias is worth having (C26).
- **Silent no-op after retries** (`Stockagent-main/agent.py:199-202`). This contradicts DRF's typed failure statuses.
- **Standalone next-day intention call** (SAP p.8 §4.2.3). SAP never analyses it. It is worth adding only if it is scored for say-do consistency (C16).
- **t-SNE plus k-means as a herding test.** It is not a metric and is not comparable across runs. Use entropy and modal share instead (item 6).
- **FCFF valuation as a simulator initialiser or modelling engine.** Use a band only as an evaluation guard. SAP's own CAPM equation has a sign error (SAP p.9 Eq.5), and the band derivation is undocumented.
- **Anonymisation as proof against leakage.** It was never tested. In DRF, masking is a probe, not a guarantee.
- **"Context cannot change disposition" as a design premise** (SAP p.21 §6.2). It rests on one run each on two old models. DRF should measure its own sensitivity (item 1) rather than import the conclusion.

### 6. Paper vs code

The repository is a partially migrated later revision. It cannot reproduce the paper as released.

| Aspect | Paper | Released code |
|---|---|---|
| Scale and assets | 200 agents, stocks A and B (SAP p.14 Table 9) | `AGENTS_NUM=50` (`Stockagent-main/util.py:161`). Prompts reference stocks C and D (`Stockagent-main/prompt/agent_prompt.py:19, 42, 76-80`) that `agent.py` never supplies, so prompt formatting likely fails |
| Models, seeds, baselines | GPT-3.5 and Gemini-pro; no seeds | Lists newer models and non-LLM baselines (`Stockagent-main/util.py:25-37`) and seeds (`Stockagent-main/util.py:144`), all unused. Only model names containing "gpt" or "gemini" are routed (`Stockagent-main/agent.py:69-73`). Temperature is 1.0 |
| Secretary | Secretary corrects invalid responses, following WarAgent (SAP p.5) | Rule-based only (`Stockagent-main/secretary.py:36-183`). Its LLM helper has an empty API key (`Stockagent-main/secretary.py:7-9`). The loan retry passes arguments in the wrong order (`Stockagent-main/agent.py:208`) |
| Settlement | Bid equals ask gives a trade (SAP p.8) | `buy_stock`/`sell_stock` are called as (name, qty, price) against the signature (name, price, amount) (`Stockagent-main/main.py:28-30, 53-54` vs `Stockagent-main/agent.py:321, 335`). Holdings move by the price, not the quantity, and failed settlements are ignored |
| Price history | Last trade of the session | Matches, but the stored history is aliased and then cleared (`Stockagent-main/stock.py:21-26`) |
| Fees and short selling | 0.005 per share; long and short allowed (SAP p.6-7) | No fees. Sells above holdings are rejected (`Stockagent-main/secretary.py:169-176`) |
| Stock B IPO | IPO pricing (SAP p.9 Eq.3) | Commented out (`Stockagent-main/main.py:79-80, 94`) |
| Bankruptcy | Sell everything and withdraw (SAP p.8) | Sells only enough to restore cash; the agent is removed only when total assets are negative (`Stockagent-main/agent.py:374-396`) |
| Loans | 1/2/3 months, simple interest (SAP p.7) | 22/44/66 days, but the prompt says years (SAP p.24). Maturity charges amount × (1 + annual rate) on top of monthly interest (`Stockagent-main/agent.py:353-372`) |
| Events | Loan cost for the companies moves from 6% to 4.5% to 5% (SAP p.8 §4.3) | Swaps the agents' global loan-rate vector on days 78 and 144, which also re-prices existing loans, and posts the event to the forum as agent -1 (`Stockagent-main/main.py:131-137`; `Stockagent-main/util.py:272-281`). Nothing fires within 10 days |
| Forum | Anonymous (SAP p.8) | Posts carry agent IDs (`Stockagent-main/main.py:189`) |
| Persona and memory | Personality shapes trading (SAP p.6-7 §4.1.2) | Personality is injected only into the skippable loan prompt (`Stockagent-main/agent.py:153, 173, 186-187`); history is cleared daily (`Stockagent-main/main.py:115`) |
| Background prompt | Opinionated first-person narrative (SAP p.25-26) | Opinion-free numeric version |
| Initial price | Valuation used as initial data (SAP p.10) | D1 band midpoints (`Stockagent-main/util.py:184-187`). Share counts are 2,000,000 and 1,000,000, against 200,000 and 100,000 in SAP Tables 3 and 5 |
| Analysis | Ablations, P&L, Figs 4-10 | No ablation switches, no P&L definition, no analysis or plotting code |

## TIEM

*Liu, Pang et al., "TIEM: Temporal Integration of Hypergraph Evidence and Skill Memory for Event-Driven Financial Forecasting", arXiv 2608.13024v5, 12 Sep 2026 (TIEM p.1).*

### 1. Essence

LLM forecasters that use retrieval or memory and are scored on historical questions can see the future in two ways. Retrieved or derived evidence can postdate the decision time (temporal leakage), and the backbone may already know the outcome (contamination). The paper calls the resulting gap between reported and real skill the "Evidence Chasm" (TIEM p.1 §1). Its task is narrow. For a catalyst c = (security, decision time T, catalyst type), predict the sign of the 3- or 5-trading-day return, with near-zero moves dropped (TIEM p.3 §3, p.4 Fig 4).

Two ideas make the paper matter, and neither is the forecasting architecture:

1. **A point-in-time input contract.** Every input gets an availability time and is gated at T:
   - Raw evidence uses its source time. The focal and same-day lane is non-strict (≤ T); prior facts are strict (< T). A date-only record counts as available at end of day.
   - A derived aggregate is available only when its latest child is.
   - An outcome-derived lesson is usable only if every case in its ancestry resolved before T. Ancestry is unioned through merges, and missing metadata fails closed.
   - A deterministic record-level audit then counts late and unverifiable inputs (TIEM p.3 §3 Fig 3, p.5 eq 10, p.20-21 App H Table 4).
2. **A nested-input probe** that asks how much of the score is reachable without the content. The inputs are name plus date, then added statistics and headlines, then added event text (TIEM p.3 §3, p.19 eq 49-51).

The three-tier hypergraph, the IF-THEN skill memory and the share-budgeted single-call fusion are the headline, but their evidence is thin (§3). For DRF, the integrity machinery is the part worth taking.

### 2. Method at a glance

```
corpus ──(once per corpus, LLM-heavy, not in the token metric)──► EEH: Day facts → Episodes (≤14 d; EDT 30 d) → Themes (90 d HDBSCAN)
3,000 resolved Astock catalysts ──chronological: forecast → resolve → distil──► CSM skills (EVOKE/MERGE, ancestry ∪) ──► frozen
test catalyst (i,T,κ) ─► gated retrieval ─► HEFR share-packer (8,000 chars + exempt concurrent lane) ─► 1 LLM call ─► p̂+ ─► direction at 0.5
          focal ≤T │ concurrent ≤T │ prior <T │ Episode/Theme τ_end<T │ skill: all ancestors <T
```

| Component | Mechanism (key settings) | Anchor | Evidence status |
|---|---|---|---|
| Catalyst-Targeted Reframing (CTR) task and label | y = sign of the Δ-day return (Δ=5; EDT 3). Returns in (−0.5%, +0.55%) are discarded. | TIEM p.3 §3; p.4 Fig 4; p.17-18 App D | Design choice; the band is neither justified nor ablated |
| CIP Gate 1 (raw) | Focal and concurrent ts ≤ T; prior Day facts ts < T; date-only means end of day. | TIEM p.3 §3; p.15 App C | Bundled into the Table 5 time-gate ablation |
| CIP Gate 2 (derived) | Episodes and Themes need τ_end < T. Skills need resolve_time < T for every ancestor, else they are excluded (fail closed). | TIEM p.3 Fig 3; p.5 eq 10; p.20 eq 61 | Audit only (Table 4) |
| CIP Gate 3 | The label never enters the input. | TIEM p.3 Fig 3 | — |
| Name-Date Probe (NDP) | E_nd ⊂ E_nc ⊂ E_full. MemBase = Acc(E_nd) vs the majority base rate; Δcontent = Acc(E_full) − Acc(E_nc) by paired bootstrap. Pools of n=968 and n=1,635. | TIEM p.3 §3; p.7 §5.3 Fig 5; p.19 eq 49-51 | Degenerate: predictions collapse to one class (§3) |
| FinPURE holdout | A-share earnings, Oct 2024 to Jan 2025. The stored price window lets labels be recomputed; name and date fields can be masked. | TIEM p.18 App D | Recent, but not after the backbones' training cutoffs |
| EEH Day tier | One LLM fact extraction per 512-token chunk. Focal = latest same-stock document ≤ T. Prior facts: over-fetch 48 by cosine, keep the first 6 same-stock with ts < T, minus the focal document. | TIEM p.3 eq 1-2; p.4 eq 5; p.21 Table 3 | Only the whole-EEH ablation |
| EEH Episode tier | Greedy, non-overlapping same-stock windows of ≤14 days (30 for EDT) with 2-7 facts, kept if ≥1 of 3 LLM votes has conf ≥0.70; k2=3. | TIEM p.3-4 eq 3; p.21 Table 3 | No tier ablation; about 0.72 retrieved per case (920/1,280, Table 4) |
| EEH Theme tier | HDBSCAN over Episode summaries in 90-day windows (30-day step). Needs ≥2 stocks and a pool of ≥50 Episodes; k3=2. | TIEM p.4 eq 4; p.21 Table 3 | About 0.23 per case (290/1,280) |
| Case-based Skill Memory (CSM) | IF-THEN skills distilled after resolution. EVOKE auto-merges at cos ≥0.85 with an EMA advantage (λ=0.9) and unions ancestry. Retrieval: q = cos·(3+a)/2, top-5, cosine floor 0.30. Frozen and read-only at evaluation. | TIEM p.4-5 eq 6-10; p.15 App C; p.18 App D | Table 2 |
| Stability diagnosis, SCMR | APPLY/MISAPPLY/SKIP diagnosis counts that set STABLE/UNSTABLE/MISS/UNEVALUABLE skill states, per-skill falsifiable reasoning paths and a weighted vote. | TIEM p.5 eq 9, 11-13; p.16 Figs 10-11 | **Disabled in every reported run** (TIEM p.15 App C, p.20 App G) |
| HEFR | Streams F, Exp, E, R, P get shares (0.20, 0.30, 0.18, 0.12, 0.20) of 8,000 characters, with surplus redistributed in priority order. The concurrent block is exempt and never truncated. Segment headers restate each stream's time contract, and the prompt includes a "may already be priced in" cue. One temperature-0 call; direction is derived from p̂+ at 0.5. | TIEM p.5 eq 14-15; p.15 App B.1; p.16 Fig 9; p.17 Alg 1; p.21 Table 3 | Table 2 |
| Audit | Every prompt record is checked as late, unverifiable or affected query, including traversal of skill ancestry. | TIEM p.20-21 App H.1, Table 4 | 0 / 0 / 0 across 1,280 cases |
| Metrics | Acc, MCC, macro-F1; shift average, worst case and ratio; Acc/ln(tokens) counting only the final call; cross-backbone agreement, Cohen's κ and dual-correct. | TIEM p.19-20 App F eq 45-60 | No Brier or log loss, although p̂+ is elicited |

### 3. What the evidence actually shows

**Headline results (TIEM p.6 Table 1; n=128 per benchmark, TIEM p.18 App D; Acc % and gap in items to the best baseline):**

| Benchmark (role) | DeepSeek-V4-Flash | GPT-5.4-mini |
|---|---|---|
| Astock (in-distribution) | 65.62 vs HippoRAG 63.28 (+3) | 65.62 vs HyperGraphRAG 61.72 (+5) |
| FinPURE (recent holdout) | 69.53 vs HyperGraphRAG 60.94 (+11) | 64.84 vs GraphRAG/HGR 58.59 (+8) |
| CMIN-US (cross-market) | 62.50 vs HGR 55.47 (+9) | 63.28 vs HGR 57.03 (+8) |
| EDT (cross-market, 3-day) | 59.38 vs HGR 55.47 (+5) | 62.50 vs HGR 57.03 (+7) |
| CSMD (cross-time) | 64.06 vs LightRAG/HGR 57.81 (+8) | 60.16 vs HGR 55.47 (+6) |
| Five-set mean (my arithmetic) | 64.2 vs 58.4 (zero-shot 51.6) | 63.3 vs 58.0 (zero-shot 50.6) |

Other reported results:
- TIEM ranks first on shift-average accuracy, worst-case accuracy and macro-F1 (TIEM p.7 Fig 6).
- It sits on both accuracy-token Pareto frontiers, counting final-call tokens only (TIEM p.8 Fig 7).
- Cross-backbone agreement is 81.88% vs 78.12%, κ 0.617 vs 0.545, dual-correct 54.69% vs 46.25% (TIEM p.8 Fig 8).
- The audit found 0 late and 0 unverifiable records across 16,301 skill ancestors and every evidence stream (TIEM p.21 Table 4).

**Ablations (Astock only):**

| Variant | DeepSeek Acc / MCC | Δ items | GPT Acc / MCC | Δ items | Anchor |
|---|---|---|---|---|---|
| Full | 65.62 / 0.31 | — | 65.62 / 0.31 | — | TIEM p.7 Table 2 |
| w/o EEH | 63.28 / 0.26 | −3 | 52.34 / 0.12 | −17 | TIEM p.7 Table 2 |
| w/o CSM | 64.06 / 0.28 | −2 | 58.59 / 0.17 | −9 | TIEM p.7 Table 2 |
| w/o HEFR | 64.84 / 0.30 | −1 | 57.03 / 0.15 | −11 | TIEM p.7 Table 2 |
| w/o time gate | 59.11 / 0.18 | ≈−8.3 | 55.73 / 0.11 | ≈−12.7 | TIEM p.21 Table 5 |

What this tells you: on the stronger backbone, each component is worth 1-3 of 128 items, which is noise. On GPT-5.4-mini the drops are large and non-additive: 37 items combined, and w/o EEH lands near zero-shot. That suggests the variants remove shared access, most likely the focal document, which comes from the Day tier (TIEM p.3 eq 1). The variants are not operationally specified.

**Validity threats, most serious first:**

1. **Sample size.** At n=128, the 95% half-width is about ±8.2-8.7 pp. Per-dataset margins are 3-11 items. Table 1 and the ablations report no CIs or significance tests, although paired tests on shared instances were available. Pooled over 640 items, the unpaired z is about 2 (my arithmetic).
2. **Run-count inconsistency.** App G says Table 1 averages 3 runs (TIEM p.20). Yet all 110 Table 1 accuracy cells are exact multiples of 1/128, while the Table 5 gate-ablation values are multiples of 1/384 (my check). So Table 1 is effectively single-run, or three identical runs, and no variance is reported.
3. **Evidence-access confound.**
   - Zero-shot and CoT receive only the catalyst query and answer from parametric knowledge (TIEM p.18 App E).
   - Memory baselines never receive the focal event body (TIEM p.22 App I).
   - Baselines time-filter only when timestamps exist (TIEM p.20 App G).
   - The authors concede that component effects cannot be isolated (TIEM p.22 §J).
   - There is no "LLM + focal text" arm. The NDP's Δcontent is about +0.21 on Astock (TIEM p.7 Fig 5b, read off the plot), so deterministic focal injection may explain much of the margin.
4. **Ablations are in-distribution.** They run only on Astock, which is also the source of the 3,000 skill-construction catalysts (TIEM p.18 App D). The skills are then reused on US datasets without any CSM ablation there.
5. **The time-gate ablation goes the wrong way.** Removing the gates lowered accuracy (TIEM p.21 Table 5). The stage-mixing explanation (TIEM p.20-21 App H.2) is untested, the amount of future evidence the ungated variant actually retrieved is not reported, and the result measures nothing about leakage inflation.
6. **The contamination probe is degenerate.** Under name plus date only, DeepSeek predicts positive about 100% of the time on both pools, and GPT about 86% on Astock and about 3% on FinPURE (TIEM p.7 Fig 5c). MemBase ≈ base rate, or GPT's ≈0.40 vs 0.604 on FinPURE, is therefore an artefact of constant output, not evidence of absent memorization. The authors say the NDP cannot exclude contamination (TIEM p.3 §3). All benchmark periods (2018 to Jan 2025) predate the 2026 backbones.
7. **The audit checks stored metadata, not truth.** Non-anticipation assumes stored timestamps equal real availability (TIEM p.12 App A.1). Availability validation is future work (TIEM p.22-23 App K). Same-day focal and concurrent records admitted at ts ≤ T could carry the day's reaction, and the Alphabet case-study win rests on decision-day facts (TIEM p.22 App I).
8. **Probabilities are never scored.** p̂+ is elicited (TIEM p.15 App B.1) but there is no Brier, log loss or ECE (TIEM p.19 App F). The value for a calibrated-probability system is unproven.
9. **Cost is understated.** The token metric excludes EEH construction and the 3,000-case skill acquisition (TIEM p.15 App C; p.19 eq 55).
10. **Other gaps.** The optional machinery is disabled, so it has zero evidence (TIEM p.15, p.20). The propositions are Gaussian and binary-symmetric-channel existence witnesses (TIEM p.12-14 App A). The excluded share of the dead band is unreported (TIEM p.3). The 4,586 focal records over 1,280 cases exceed k_F=1, which is unexplained (TIEM p.21 Tables 3-4).

**Net:** there is directional support that gated, multi-source context beats flat RAG and memory baselines under unequal access. There is solid support that a complete-ancestry temporal audit is cheap and can be tabulated. There is no support for probability quality or for the disabled lifecycle components.

### 4. Mechanisms worth transplanting to DRF, ranked

Order follows dependency. Integrity first, then measurement, then the one forecasting-side change, whose effect cannot be seen until the first five exist.

| Rank | PID | Transplant | Status | Verifier value | Related |
|---|---|---|---|---|---|
| 1 | P01 | Point-in-time (PIT) evidence gates with availability semantics | absent | 3 | C08, C18, C35 |
| 2 | P05 | Deterministic temporal audit with fail-closed evaluation admission | absent | 3 | — |
| 3 | P03 | Nested closed-book contamination probes, scored with Brier | absent | 3 | C21 |
| 4 | P04 | Ancestry-gated recalibration and frozen learned-state snapshots | partial | 2 | C03 |
| 5 | P06 | Golden-eval statistical rigor | partial | 3 | C40 |
| 6 | P09 | Share-based evidence packer with an exempt "latest developments ≤ as_of" lane | partial | 4 | — |
| 7 | P17 | Golden set v2 (recomputable labels, dead-band ambiguity, balance) | partial | 3 | — |
| 8 | P20 | Full-pipeline cost-quality accounting | partial | 3 | — |
| 9 | P15 | Backbone-sensitivity flags | partial | 3 | — |
| 10 | P16 | Lessons ledger with ancestry-gated retrieval | absent | 1 | C03 |

**1. P01: PIT gates (extends C08/C18/C35).** Proposed default-off eval flag.

*What TIEM contributes:*
- per-stream gate semantics;
- derived records inherit their latest child's time (TIEM p.4 eq 4);
- over-fetch then filter (TIEM p.3 eq 2);
- fail closed on missing or invalid skill-ancestry time (TIEM p.15 App C).

*Where DRF cannot enforce as_of today:*
- Research v3 stamps today's date as the plan's as_of (`deerflow_bridge/linear_research.py:4212-4217`, `_utc_date` at `:533-534`), although golden_eval tells users to run with an as-of constraint (`backend/scripts/golden_eval.py:19-22`).
- Every cited source is written with `"date": None` (`deerflow_bridge/linear_research.py:5580-5593`).
- Published/Updated datelines are discarded as page chrome (`:2761-2764`, `:2774-2776`).
- `_validate_as_of_date` moves the anchor forward to the newest source date instead of dropping late sources (`backend/app/services/pipeline_orchestrator.py:10824-10832`).
- `annotate_recency_rows` puts future-dated rows (negative age) into the "fresh" bucket (`deerflow_bridge/deerflow_research.py:9928-9933`).
- The page cache is keyed by URL only, with a 72-hour cross-run TTL, so a PIT run can be served a live page (`deerflow_bridge/cached_fetch.py:56`, `:560-567`, `:580-582`).

*Transplant:*
- Capture datelines as availability metadata before stripping (C18). If an "Updated" date is after as_of, the page is unavailable.
- Use strict < as_of for all research evidence. DRF has no focal document at T, so any same-day lane is a declared exception.
- Date-only means end of day; month or quarter means end of period; undated sources are quarantined.
- Timeline rows, quantitative_facts, actors.json claims and Graphiti episodes inherit max(source availability).
- Keep availability separate from event time. The existing `search_filter` as-of pushdown filters only on the event-time validity window (`valid_at` ≤ as_of, `invalid_at` null or later), not on availability time (`backend/app/services/zep_tools.py:909-916`).
- Over-fetch and filter before fetching, so post-as_of pages never enter the cache.
- Polymarket anchors use prices-history points with t ≤ as_of (`backend/app/utils/prediction_markets.py:420-432`) and reject markets past endDate (C35).

*Evidence:* this is an integrity requirement, not a measured gain (Table 5 runs the "wrong" way).

**2. P05: temporal audit.** An LLM-free post-stage writes `temporal_audit.json` as {stream: {checked, late, unverifiable, affected_forecasts}}, mirroring TIEM Table 4 and eq 61 (TIEM p.20-21).
- **Streams walked:** sources.json, quantitative_facts, timeline, actors.json refs, Graphiti reference_times, Polymarket snapshot times, and any ledger rows a recalibration used.
- **Admission rule:** any LATE record keeps the run out of scoring, or tags it `characterization_only`, a flag the ledger already honours (`backend/app/services/forecast_ledger.py:49-60`). UNVERIFIABLE records above a threshold mark the run `pit_unverified`.
- **Today:** every current golden run would come out fully unverifiable, which is the honest status under DRF's fail-closed stance (`DRF_ARCHITECTURE.md:1737-1741`).
- **Canary:** diff gate-on against gate-off on 3-5 questions. If gate-off improves Brier, a leak is live. A null result proves nothing.

**3. P03: contamination probes (extends C21).** Three arms per golden question:
- E_nd: question plus as_of, closed book, one call;
- E_nc: adds reference-class base rates and the market price at as_of;
- E_full: the pipeline.

Score with Brier and log score, not accuracy, and compare E_nd against climatology. Report the paired-bootstrap ΔBrier(E_nc→E_full) as the value research adds. Add a dispersion check (share of probabilities in [0.4, 0.6], standard deviation) so a constant-output probe is not read as clean, which is TIEM's Fig 5c flaw. Flag questions where E_nd is confident and correct, and report them separately. Optional extras: a one-call recall probe and a masked-entity arm (C21).

This is urgent. The golden set is 30 questions with as_of dates from 2024-01-01 to 2025-02-01 (`backend/tests/eval/golden_questions.json:2-7`), for example us-pres-2024-trump at as_of 2024-11-01 (`:10-17`). EVAL-1 Brier currently mixes recall with forecasting skill. The probe's scoring fits `golden_eval.py`'s pure core (`backend/scripts/golden_eval.py:147-183`).

**4. P04: ancestry-gated learned state (extends C03).**
- **Today:** `recalibration_param` fits every resolved production row with no time filter (`backend/app/services/forecast_ledger.py:277-309`, filter `:291-296`). `fit_recalibrator` fits in-sample once there are ≥10 points (`backend/app/services/backtest.py:188-227`, `:215-216`). Golden rows carry only `created_at=as_of_date` and `resolution_date` (`backend/app/services/forecast_ledger.py:148-168`).
- **The leak is latent.** No caller applies the fit, and the flag is read through `getattr` with a False default (`:297-302`). So the gate must land before anyone wires recalibration in.
- **Rule:** a row counts only if its resolve time and created_at parse and are strictly < as_of. Stamp the contributing row ids and a `data_horizon` on the fit; this is TIEM's ancestry A (TIEM p.4 eq 6).
- **Frozen snapshot:** hash the learned state into eval_report.json before a golden batch, with no writes during the batch (TIEM p.15 App C).

**5. P06: statistical rigor (extends C40).** TIEM is the cautionary case: ±8.7 pp at n=128 and no CIs. DRF's n=30 has 24 YES outcomes (my count), so a constant 0.8 already scores Brier 0.16. `score_pairs` reports `base_rate` but no climatology Brier, Brier skill score (BSS), CIs or paired comparisons (`backend/scripts/golden_eval.py:147-183`).

Add:
- climatology Brier and BSS;
- predicted-YES rate vs realized rate, and a hedge-collapse share;
- bootstrap CIs stratified by category and clustered by question (TIEM's within-dataset resampling, TIEM p.20 App F);
- paired ΔBrier for version A/B comparisons;
- worst-category Brier read together with absolute levels (TIEM p.19 eq 52-54);
- at least 3 repeats per arm with fingerprints, so a "mean of 3" cannot silently be one run.

**6. P09: evidence packer.**
- **Today:** binary extraction keeps the first 60% and last 40% of a 48,000-character budget (28,800 head plus 19,200 tail characters) and drops the middle of any longer dossier (`backend/app/services/forecast_extractor.py:943-967`, `:2649-2651`). `slice_budget_chars` has per-slice shares but no cross-stream allocator or exempt lane (`backend/app/utils/token_budget.py:77-86`, `:140-152`).
- **Transplant:** HEFR's scheme (TIEM p.5 §4.3):
  - named streams with fixed character shares and surplus redistributed in priority order;
  - per-stream truncation telemetry, per DRF's "no silent truncation" value (`DRF_ARCHITECTURE.md:1758-1760`);
  - a budget-exempt "latest developments ≤ as_of" lane chosen by recency per key actor, TIEM's focal and concurrent design (TIEM p.3 eq 1; p.4 eq 5; p.5 §4.3);
  - segment headers that state the temporal contract;
  - yes/no derived from the stated probability;
  - a "may already be priced in" line for market-anchored binaries, feeding `enforce_market_divergence` (`backend/app/services/forecast_extractor.py:1831`).
- **Evidence:** weak. HEFR is worth 1/128 items on DeepSeek, and the motivation is a single case study (TIEM p.22). Ship behind a flag only after a P06-grade golden A/B.

**7. P17: golden set v2.** The schema has 8 fields (`backend/tests/eval/golden_questions.json:5`); 11 of 30 questions are elections and 24 resolved YES.
- Add resolve_time, resolution_evidence (URL, archived snapshot, raw value) so labels can be recomputed, as FinPURE's stored price windows allow (TIEM p.18 App D).
- Add maskable_fields for P03 and a shift_axis.
- For numeric thresholds, use a tolerance dead-band: an outcome within ε of the threshold is ambiguous and excluded from Brier and from fitting. Do not copy TIEM's asymmetric band.
- Rebalance the outcome mix.
- Report DRF's prospective resolutions ledger (`backend/app/services/forecast_ledger.py:369-399`) separately, as the only contamination-free benchmark.

**8. P20: cost-quality accounting.** TIEM's final-call-only token count (TIEM p.19 eq 55) is exactly what DRF must not copy, because research was about 96% of tokens before engine v3. Use the per-stage LLMMeter telemetry (`backend/app/utils/telemetry.py:223-240`, `:437-450`) to report full-pipeline tokens and dollars per question. Report ΔBSS per 1k tokens against the P03 E_nd arm, a Pareto frontier over configurations, and compute-matched controls.

**9. P15: backbone sensitivity.**
- **TIEM's metrics:** agreement, κ and dual-correct (TIEM p.20 eq 58-60).
- **Today:** `pool_binary_forecasts` already records per-model probabilities and their standard deviation, and flags a binary as low-agreement when the standard deviation exceeds 0.15 (`backend/app/services/ensemble.py:261-345`).
- **Add:** a sign-flip-across-0.5 `backbone_disagreement` flag, batch κ, mean |Δp| and golden dual-correct.
- **Sim signals:** zeroing flipped sim signals matters only in `legacy_prompt` mode. By default the simulation is `diagnostic_only` and cannot move published probabilities (`backend/app/services/forecast_extractor.py:2657-2660`; `backend/app/config.py:1483-1485`).
- **Evidence:** descriptive only.

**10. P16: lessons ledger (extends C03).** Keep three things only:
- the ancestry discipline, via P04;
- the retrieval rule q = cos·(3+a)/2 with top-5 and a cosine floor (TIEM p.5 eq 10; p.21 Table 3);
- the path-reasoning prompt pattern (relevance ≠ correctness, flip on contradiction, abstain when thin; TIEM p.16 Fig 11), folded into existing critique prompts at zero extra calls.

CSM moved 2/128 items in-distribution. DRF lacks the resolved-case volume that TIEM had (3,000 cases). Golden-derived lessons must never load in production.

### 5. What not to transplant, and why

- **The EEH construction pipeline** (per-chunk fact extraction, 3-vote Episodes, HDBSCAN Themes, n-ary hyperedges). It is LLM-heavy and excluded from TIEM's own cost accounting (TIEM p.15 App C; p.19 eq 55). It has no per-tier ablation, and its upper tiers were barely used (0.72 Episodes and 0.23 Themes per case, TIEM p.21 Table 4). Themes need a pool of ≥50 Episodes (TIEM p.21 Table 3), which one question with ≤20 actors never reaches. DRF's Graphiti temporal KG already covers this. At most, add a deterministic per-actor episode stream inside P09 if an A/B justifies it.
- **SCMR and stability diagnosis.** They were disabled in every run (TIEM p.15, p.20), cost 2 extra calls per skill and return a direction, not a probability.
- **A full CSM lifecycle now.** It has weak and in-distribution evidence, skill catalysts randomly sampled from Astock, the same dataset and 2018-2020 window as its test set (TIEM p.17-18 App D), cross-market reuse that was never tested, and DRF has too few resolutions to feed it.
- **Accuracy, MCC and F1 as the target, and the accuracy-scored NDP.** DRF is a probability system, and TIEM never scores p̂+.
- **The asymmetric (−0.5%, +0.55%) dead band.** It is unjustified and its excluded share is unreported (TIEM p.3). Use a tolerance-based ambiguity rule instead (P17).
- **A non-strict same-day lane as default.** DRF has no focal document at T, and same-day items can carry the outcome. Keep strict < as_of.
- **Reading the gate ablation as a leakage estimate, or a 0-late audit as proof of cleanliness.** The first ran the wrong way; the second verifies stored timestamps only (TIEM p.12 App A.1).
- **Final-call-only token metrics.** They hide DRF's dominant research cost (see P20).
- **HEFR's single temperature-0 call as a replacement for DRF's report spine.** It was built for one short-horizon binary. DRF needs MECE scenarios plus ≥10 calibrated binaries.
- **The propositions as design justification.** They are toy-model existence witnesses (TIEM p.12-14 App A).

## Nexus

*Nexus: An Agentic Framework for Time Series Forecasting.* Das, Goyal, Parmar et al., Google and Penn State, arXiv 2605.14389, May 2026. Key: **NEX**. External facts that are not in the paper are marked "(external, verify)".

### 1. Essence

Nexus asks whether a frontier LLM, with no statistical model underneath it, can forecast a numeric weekly series as well as a time-series foundation model and also explain what drives the forecast (NEX p.1 abstract; p.3 §2; p.6 Table 1). The test series are Zillow metro sale-inventory counts and stock closes, optionally with a text stream aligned to each step. The paper's answer is to split one monolithic prompt into four LLM roles:

- A context agent rewrites the history into a dated timeline in which each value is tied to its drivers.
- Two forecasters draft the horizon at different resolutions: one as a trajectory for the whole horizon, one as a step-by-step walk through expected catalysts.
- A synthesizer reconciles the two drafts and must say how it weighted them.
- A calibration agent turns walk-forward backtest errors into short correction rules. It sees each draft's error, keeps only the rules common to all training folds, and applies them only if they improve the most recent held-out fold by at least 5% (NEX p.3-5 §3; p.7 §4.1; p.17 App. B.4).

Two ideas make the paper matter for DRF, and neither is the forecasting architecture itself:

1. **Learned corrections under a gate.** Corrections are learned from errors, the critic sees each component's error, and a correction must pass a held-out, time-ordered gate before it touches live forecasts.
2. **An evaluation stance.** Score only targets that fall after the model's knowledge cutoff, and treat agreement between the narrative and the numbers as a property that can be checked.

The architecture is weakly supported. Each component's measured contribution is 1-4% relative MAPE, from one run, on one horizon, with one model (NEX p.9 Table 5; p.15 App. A). Much of the paper's value to DRF therefore comes from its gaps: it trusts declared cutoffs, reports single runs, scores point forecasts only, and uses a judge that sees the outcomes.

### 2. Method at a glance

```
(X_1:τ values, E_1:τ per-step text) ─► A_ctx ─► H (dated timeline: date | value | drivers)
                                               ├─► A_macro ─► whole-horizon path + narrative ─┐
                                               ├─► A_micro ─► per-step JSON path + events ────┼─► A_syn(·, G) ─► final path X̂ + rationale R
                                               └──────────────── skip link (H) ───────────────┘
history cut into n=6 time-ordered splits: folds 1..5 ─► A_calib ─► G_1..G_5 ─► ∩ ─► gate on fold 6 (≥5% gain) ─► G (else empty)
```

| # | Component | Input → output | Contract details that matter | Anchor |
|---|---|---|---|---|
| 0 | Task | univariate series plus per-step text → T future values plus rationale R | Weekly steps, point forecasts only | NEX p.3 §2; p.6 Table 1 |
| 1 | Historical Context Agent (A_ctx) | raw values, text and `{ts_features}` → timeline H with one entry per step: date, value, summary of drivers | Told to drop no fact; `{ts_features}` is never defined | NEX p.3-4 §3.1; p.15 App. B.1 |
| 2a | Macro agent | H → path for the whole horizon plus narrative | Reasoning tag, then an array of exactly T values. The prompt is nearly the CoT prompt, but asks for exhaustive rather than brief reasoning | NEX p.4 §3.2; p.16 App. B.2; p.18-19 App. C |
| 2b | Micro agent | H → JSON with one entry per step: date, `day_info` event, Up/Down/Stable label, key driver, value | Future events are guessed by the model, not retrieved | NEX p.4-5 §3.2; p.16-17 App. B.3 |
| 3 | Synthesizer (called "Value Predictor" in the appendix) | H, both drafts (numbers and reasoning) and guidelines G → final path | Drafts are advisory ("for reference"); must explain per step how it adjusted each draft; required future dates listed | NEX p.5 §3.3; p.17-18 App. B.5 |
| 4 | Calibration agent | per training fold: the synthesizer's prompt, reasoning, values and MAPE, the macro and micro MAPE, and the true events and values → a diagnosis plus one generalized guideline paragraph | n=6 splits, last one hidden; the 5 fold guideline sets are intersected (method not specified); applied only if they improve the hidden fold by ≥5% | NEX p.5 §3.3; p.7 §4.1; p.17 App. B.4 |
| E | Evaluation | Gemini-3.1-Pro and Claude-4.5-Sonnet at temperature 0.1, single run; targets from Feb 2025 on; MAPE/RMSE; baselines are a CoT prompt and TimesFM-2.5 (numbers only); cross-family pairwise judge | At least 4 LLM calls per forecast plus the fold backtests, against 1 call for CoT; cost not reported | NEX p.5-7 §4.1; p.8-9 §4.4; p.15 App. A |

### 3. What the evidence actually shows

**Headline accuracy.** Average MAPE over three horizons: Zillow 4/8/13 weeks, stocks 6/13/26 weeks.

| Setting | Model | Domain | CoT | TimesFM-2.5 | Nexus | Nexus vs best baseline | Anchor |
|---|---|---|---|---|---|---|---|
| Text | Gemini | Zillow | 0.0423 | — | 0.0361 | −14.7% | NEX p.7 Table 2a |
| Text | Gemini | Stocks | 0.1122 | — | 0.1109 | −1.2%; **loses at 26 weeks** (0.1379 vs 0.1357) | NEX p.7 Table 2a |
| Text | Claude | Zillow | 0.2968 | — | 0.0398 | −86.6%, because the baseline collapses | NEX p.7 Table 2b |
| Text | Claude | Stocks | 0.1368 | — | 0.1204 | −12.0%; **loses at 13 weeks** (0.1155 vs 0.1113) | NEX p.7 Table 2b |
| Numbers | Gemini | Zillow | 0.0422 | 0.0387 | 0.0378 | −2.3% vs TimesFM; long-horizon RMSE tied (64.5105 vs 64.5095) | NEX p.8 Table 3a |
| Numbers | Gemini | Stocks | 0.1334 | 0.1294 | 0.1238 | −4.3% vs TimesFM, **all of it from 26 weeks**; TimesFM wins at 6 weeks (0.0841 vs 0.0868) and 13 weeks (0.1207 vs 0.1249) | NEX p.8 Table 3a |
| Numbers | Claude | Zillow | 0.1663 | 0.0387 | 0.0330 | −14.7% vs TimesFM, the strongest result against a competent baseline | NEX p.8 Table 3b |
| Numbers | Claude | Stocks | 0.1201 | 0.1294 | 0.1189 | −1.0% vs CoT; CoT wins at 13 weeks; three-way tie at 6 weeks (0.0839-0.0841) | NEX p.8 Table 3b |

**Text context is model-dependent.** This is my comparison across Tables 2 and 3; the authors do not discuss it. Adding text helps Nexus with Gemini: Zillow −4.5% and stocks −10.4% MAPE. It hurts Nexus with Claude: Zillow +20.6% and stocks +1.3% (NEX p.7-8).

**Reasoning judge.** Overall preference for Nexus over CoT was 63.5% and 97.1% for Gemini outputs (stocks, Zillow) and 79.8% and 88.5% for Claude outputs (NEX p.9 Table 4). On Logic-to-Number Consistency, CoT won only 3.8%, 2.5% and 1.8% of pairs in three of the four cells, against 33.1% on Gemini stocks (NEX p.9 Table 4).

**Ablations: which components matter, and by how much.** Gemini, text setting, short horizon only, single run (NEX p.9 Table 5; p.15 App. A). The last column is my calculation against CoT's short-horizon MAPE of 0.0351 (Zillow) and 0.0904 (stocks) (NEX p.7 Table 2a).

| Variant | Zillow MAPE (relative Δ) | Stocks MAPE (relative Δ) | Share of full Nexus's gain over CoT still retained (Zillow / stocks) |
|---|---|---|---|
| Full | 0.0306 | 0.0866 | 100% / 100% |
| without macro | 0.0317 (+3.6%) | 0.0882 (+1.8%) | 76% / 58% |
| without micro | 0.0314 (+2.6%) | 0.0877 (+1.3%) | 82% / 71% |
| without calibration | 0.0309 (+1.0%) | 0.0877 (+1.3%) | 93% / 71% |

Absolute deltas are 0.0003-0.0016 MAPE. Most of the gain survives removing any one component, so it comes from the shared scaffolding: the timeline, the synthesizer, and heavier, multi-call prompting. The dual-resolution split and calibration contribute little. The paper never ablates the context agent, never compares the synthesizer with a plain average or with picking the better draft, and never varies n, k or the intersection rule (NEX p.9 §4.5).

**Validity threats**

- **Noise.** All results are single runs with no CIs, which the authors attribute to cost (NEX p.15 App. A). The ablation deltas and the −1.2% stock gain for Gemini cannot be separated from sampling noise.
- **Small, correlated samples.** The data are 15 metros and 7 tickers over one 2025 window. Weekly rolling origins overlap heavily, with horizons of up to 26 weeks (NEX p.6 Table 1), so the effective sample for stocks is closer to 7 price paths than to 693 windows. The authors say themselves that the stocks mostly followed a long-term trend (NEX p.8).
- **Weak or brittle baselines.** Claude's CoT also collapses in the numbers-only setting (Zillow MAPE 0.1663; NEX p.8 Table 3b), where its input is only about 156 weekly values (3-year context; NEX p.6 Table 1). This fits the authors' long-context explanation poorly (NEX p.7-8 §4.2) and suggests prompt or parse brittleness; no parse-failure rates are given (my inference). There is no persistence, seasonal-naive, ETS or ARIMA baseline, and TimesFM gets no covariates.
- **Compute and prompt asymmetry.** Nexus makes at least 4 calls plus 6 backtest folds; the baseline makes 1 call and is told to keep its analysis brief, while the Nexus agents are told to be exhaustive (NEX p.16-19 App. B-C; p.7 §4.1). There is no compute-matched CoT or self-consistency control.
- **Leakage control is declarative.**
  - Targets begin the month after the declared January 2025 cutoff (NEX p.6). No memorization probe is run, and the authors call leakage highly probable in general (NEX p.15 App. A).
  - Anthropic publishes a later training-data cutoff for Sonnet 4.5 (about July 2025) than its reliable-knowledge cutoff (external, verify), which would overlap the evaluation window.
  - The NFLX series is plotted at roughly 70-130 (NEX p.21 Fig. 3d) and the model reasons toward "the 115 range" (NEX p.26 F.4). That scale is consistent with prices adjusted after the fact for a later 10:1 split (external, verify), in which case the context values were not observable at the forecast origin.
  - How the text stream was sourced and dated is only referenced to TFRBench (NEX p.7).
- **Judge bias.**
  - The judge sees the events that actually happened but not the values, and is told to ignore accuracy (NEX p.19 App. D). This rewards narratives consistent with hindsight, including ones produced by leakage.
  - The verbosity asymmetry above also favours Nexus. There is no human validation and no item count.
  - Gemini's Zillow reasoning won 97.1% overall (NEX p.9 Table 4), yet an LA trace from Nexus (model not stated) credits sale inventory to the Super Bowl, the Oscars, the LA Marathon and Coachella (NEX p.27 F.6).
- **Confident misses in the showcase figures.** The showcase win is MSFT at 26 weeks: Nexus 0.104, TimesFM 0.186, CoT 0.249 (NEX p.20 Fig. 3a). But on RKLB at 6 weeks, both LLM methods project a rise to about 79 while the price falls to about 40, and the flat TimesFM line is closest (NEX p.24 Fig. 3m). The matching trace walks confidently from 66.50 to 78.40, citing analyst price targets (NEX p.29 F.13). No failure analysis is given.
- **The calibration step is uncharacterized.** The intersection of free-text guidelines is never operationalized. The gate metric is unnamed. No learned guideline and no acceptance rate is shown. Agent names drift ("Sanity Check Agent", "Value Predictor"; NEX p.17), and the placeholders `{ts_features}` and `{event_predictions_section}` are undefined (NEX p.15, p.18). No code is linked.
- **Scope.** Outputs are point forecasts only. "Calibration" here means rule learning, not probabilistic calibration. There is no evidence for event or binary questions.

**Net reading.** Supported: a structured multi-call LLM pipeline beat this particular single-prompt CoT on average in all 8 model × domain × setting cells (NEX p.7-8), and was roughly on par with TimesFM-2.5 given numbers only. Not supported:

- that any individual component matters;
- that text context generally helps;
- that judged reasoning quality tracks accuracy;
- anything about uncertainty, calibration or binary outcomes.

### 4. Mechanisms worth transplanting to DRF (ranked)

Ranking rule: validity and cheap integrity checks come first. Architectural transplants come last, because their evidence is weakest and they cannot be measured until ranks 1-6 exist.

| Rank | Mechanism (Nexus source) | Candidate | DRF status | Evidence | Cost |
|---|---|---|---|---|---|
| 1 | Post-cutoff, point-in-time golden scoring (NEX p.6 §4.1) | P02 + P01, P03 (C08, C18, C35, C21) | absent | Validity precondition; the paper never measures it | medium, deterministic |
| 2 | Deterministic logic-to-number lint (NEX p.19 App. D; p.9 Table 4) | P08 | partial (numeric-only checks) | indirect | low, no tokens |
| 3 | Per-model channel value-add arms, compute-matched controls, cost denominator (NEX p.7-8) | P07 + P20 (C30) | partial | single-run, model-dependent effect | medium (eval runs) |
| 4 | Golden-eval statistical rigor (NEX p.15 as the counter-example) | P06 (C40) | partial | methodological | low |
| 5 | Held-out, most-recent-fold acceptance gate for learned state (NEX p.5 §3.3) | P04 (C03) | partial | integrity | low |
| 6 | Quantile scoring for numeric targets (NEX p.7 as the counter-example) | P14 | absent | methodological | low |
| 7 | Numeric-quantity lane (NEX p.3-4 §3.1; p.4 §3.2) | P12 (C24) | absent | modest | medium-high |
| 8 | Per-channel probability cards persisted in the ledger (NEX p.17-18 App. B.4-B.5) | P11 (C25, C14) | partial | weak | medium |
| 9 | Dual-resolution spine over a sourced catalyst calendar (NEX p.4-5 §3.2) | P19 | partial | weak (1.3-3.6%) | medium |
| 10 | Hardened judge protocol (NEX p.8-9 §4.4) | P18 | partial | methodological | low |
| 11 | Lessons ledger learned from errors (NEX p.5 §3.3; p.17 App. B.4) | P16 (C03) | absent | weakest (about 1%) | medium, offline |

**1. Post-cutoff, point-in-time golden scoring: P02, with P01 and P03 (C08, C18, C35, C21).**

*What Nexus does.* Its only leakage control is choosing models with a declared cutoff, placing every target after it, and stating the cutoff in each forecasting agent's system prompt (NEX p.6 §4.1; p.15-18 App. B). The micro agent's dated per-step events would make a natural audit surface (NEX p.16-17 App. B.3), but the paper never uses them that way.

*DRF today.*

- The golden set has 30 questions. Their as_of dates run from 2024-01-01 to 2025-02-01, they resolve between 2024-01-10 and 2025-02-09, and 24 resolved YES (backend/tests/eval/golden_questions.json:1-310, computed). That is very likely before the cutoffs of the default backbones (backend/app/config.py:739-769), so golden Brier currently mixes recall with forecasting skill.
- The harness requires an as-of run (backend/scripts/golden_eval.py:19-24), but research v3 always plans with as_of set to today (deerflow_bridge/linear_research.py:4211-4216).
- v3 writes `date: None` for every source (deerflow_bridge/linear_research.py:5585-5595), so the evidence-date guard in `_validate_as_of_date` cannot fire. When it does fire, it moves the anchor *forward* to the newest source date (backend/app/services/pipeline_orchestrator.py:10808-10837).
- `annotate_recency_rows` counts rows dated after as_of (negative age) as fresh (deerflow_bridge/deerflow_research.py:9928-9933).
- Golden ledger rows record no model id (backend/app/services/forecast_ledger.py:148-168).

*Transplant.*

- (a) Keep a registry `{model_id: training_data_cutoff (take the later of the published dates), source}`, keyed on the per-call model ids that LLMMeter already records (backend/app/utils/llm_client.py:484-489). Stamp the models and their cutoffs on every golden row.
- (b) In golden_eval, compute headline Brier, log score and ECE only for rows where as_of is later than the latest cutoff of any model that touched the run, plus at least 60 days. Report the other rows as characterization only. If a cutoff is unknown, print no headline number (fail closed).
- (c) PIT mode (P01):
  - treat negative age as LATE and drop the row;
  - exclude undated sources;
  - add a `vintage_date` to quantitative_facts;
  - use the Polymarket price at as_of (C35);
  - derived artifacts inherit the latest availability time of their sources.
- (d) Contamination probes (P03):
  - add a closed-book arm and a one-call recall probe;
  - classify dated in-horizon events in scenarios and binaries as sourced (evidence dated at or before as_of) or unsourced;
  - flag an unsourced event that matches the outcome as a possible leak.
- (e) Add one fixed-prefix AS_OF block to stage prompts (the spine prompt has none today; backend/app/services/forecast_extractor.py:3180-3212), placed so prompt caching still works. This is framing, not a control.

*Evidence.* This is an integrity precondition; neither the paper nor DRF measures its effect. Every Brier comparison in ranks 3-11 depends on it.

**2. Deterministic logic-to-number lint: P08.**

*What Nexus does.* Judge criterion 3 asks whether the narrative's direction and size match the model's own numbers (NEX p.19 App. D). CoT won it in only 1.8-3.8% of pairs in three of the four cells, and 33.1% on Gemini stocks (NEX p.9 Table 4), so single-prompt narratives often contradict their own numbers. The micro agent's Up/Down/Stable label next to each value (NEX p.17 App. B.3) makes a deterministic check possible, although the paper only ever uses an LLM judge for it.

*DRF today.* The checks are numeric only. `check_scenario_probabilities` compares percentages near a scenario name with the spine, within ±1 point (backend/app/services/report_lint.py:781-809). `_synchronize_scenario_probability_narratives` rewrites stale numeric targets in critique prose (backend/app/services/forecast_extractor.py:532-572). There is no verbal-likelihood lexicon anywhere in app/services or app/utils (grep).

*Transplant.*

- A bilingual lexicon that maps likelihood phrases to bands: likely ≥ ~0.55, unlikely ≤ ~0.45, almost certain ≥ ~0.9, plus the Chinese equivalents.
- Sentence-level binding of each phrase to the nearest scenario name or binary id.
- Ranking words checked against the MECE probability order.
- Direction and magnitude words, and any Up/Down/Stable movement label, checked against the numeric change from the as-of value (once rank 7 produces quantity paths).
- Rollout: run warn-only first and measure the flag rate on existing reports. Then block in the epistemic tier of the publish gate above a threshold, or allow one bounded restatement. Run the lint before the stabilizer and final audit so fingerprints stay valid.

It costs no tokens.

*Evidence.* Indirect (judge-based and confounded by prompt length); the bands are untested.

**3. Per-model channel value-add arms, compute-matched controls and a cost denominator: P07 + P20 (C30).**

*What Nexus does.* Text helped Nexus with Gemini and hurt it with Claude (§3). Nexus also compared at least 4 calls plus 6 folds against a single brief call, with no cost reported (NEX p.4 Fig. 2; p.7 §4.1; p.18-19 App. C; p.15 App. A).

*DRF today.* The spine concatenates five optional context blocks, each with its own character cap (backend/app/services/forecast_extractor.py:3176-3203). DRF serves several model families (backend/app/config.py:739-769) and has an optional multi-model binary ensemble (backend/app/config.py:636-645). Nothing measures a block's marginal Brier for each model.

*Transplant.*

- On the post-cutoff subset from rank 1, run these arms for each backbone: closed-book → research-only → +graph → +sim → +market anchor.
- Add a single-prompt floor with the same token budget as the multi-call variant, and an A/A duplicate to measure the noise floor.
- Replay retrieval from a frozen snapshot, so arms differ only in the channel under test.
- Switch a block on by default for a given model only if the paired ΔBrier CI excludes zero.
- Record full-pipeline tokens and dollars per question (research, graph, sim, report) from LLMMeter, and choose defaults from a Pareto frontier of Brier skill against cost.

**4. Golden-eval statistical rigor: P06 (C40).**

*What Nexus does, as a counter-example.* Single runs, overlapping windows, and reversals hidden inside averages (§3). Its one good habit is reporting per horizon (NEX p.7-8).

*DRF today.* `score_pairs` reports mean Brier, log score, accuracy at 0.5 and base rate, broken down by category and difficulty (backend/scripts/golden_eval.py:147-204). There is no climatology skill score, no CI, no horizon bucket and no repeated run. With 24 of 30 questions resolving YES, a constant 0.8 already scores Brier 0.16.

*Transplant.*

- Brier skill score against climatology.
- Predicted-YES rate against realized YES rate.
- Category-stratified bootstrap CIs, clustered by question.
- Paired ΔBrier for comparing versions.
- At least 3 runs per arm, with the spread reported.
- Horizon buckets: ≤30 days, 31-180 days, >180 days.
- Invalid-output rate per arm.
- A directional-bias monitor (share of YES/up calls against realized outcomes). The confident bullish RKLB miss (NEX p.24 Fig. 3m) is the failure it targets.
- A lint that recomputes every headline aggregate from the per-row data.

**5. Held-out, most-recent-fold acceptance gate for all learned state: P04 (C03).**

*What Nexus does.* Learned guidelines are adopted only if they improve the hidden last fold by at least 5%; otherwise the guideline set stays empty (NEX p.5 §3.3; p.7 §4.1).

*DRF today.*

- `fit_recalibrator` fits a logit slope in-sample once there are at least 10 points. Points are counted per scenario, so five binary questions are enough (backend/app/services/backtest.py:200-227).
- `recalibration_param` fits every resolved production row, with no as_of filter (backend/app/services/forecast_ledger.py:277-311).
- The recalibrator is currently inert:
  - `REPORT_RECALIBRATE_FROM_LEDGER` is read with getattr but never defined on Config (backend/app/services/forecast_ledger.py:297-302; grep);
  - `apply_recalibration` has no runtime caller (backend/app/services/backtest.py:230-237; grep);
  - resolution never flips ledger rows to resolved (docs/foglamp/current-shape-map.md:82).

*Transplant, before anything is switched on.*

- Split resolved rows by resolution date: fit on the oldest ~80%, validate on the newest ~20%.
- Accept the slope only if validation Brier or log score improves by at least k%, with n_val ≥ ~20 and a bootstrap CI that excludes zero. Otherwise keep the identity slope.
- Stamp `{slope, fit_n, val_n, delta, data_horizon, decision}` into report provenance.
- In replays, assert `data_horizon < run.as_of`.
- Snapshot and hash learned state before each golden batch.
- Use the same gate for prompt and policy promotions, consistent with the promotion-gate stance already written into config (backend/app/config.py:330-333).

**6. Quantile scoring for numeric targets: P14.**

*What Nexus does, as a counter-example.* Point MAPE and RMSE only, with RMSE averaged across entities of very different scale, and no persistence baseline (NEX p.7 §4.1). TimesFM beat Nexus at 6 and 13 weeks on stocks (NEX p.8 Table 3a).

*DRF today.* Scoring covers scenarios and binaries only (backend/app/services/backtest.py:41-70; backend/scripts/golden_eval.py:147-182).

*Transplant.*

- Store `{quantity_id, unit, target_date, as_of_value, p10, p50, p90}` in forecast.json and in the ledger.
- At resolution, compute the absolute percentage error of the median, pinball loss per quantile, 80%-interval coverage, and skill against both a no-change forecast (the as-of value) and the market-implied value.
- Keep Brier for threshold binaries derived from the quantiles.

This must land before rank 7.

**7. Numeric-quantity lane: P12 (C24).**

*What Nexus does.* A timeline that ties each value to its causes (NEX p.3-4 §3.1; p.15 App. B.1), a slot for time-series features (NEX p.15), and a regime draft for the whole horizon (NEX p.4 §3.2).

*DRF today.* RESEARCH extracts two things separately (deerflow_bridge/linear_research.py:470-480, 5726-5756):

- `quantitative_facts` with fields `{metric, value, unit, as_of_date, period_end, value_type, source_ref}`;
- `key_events` with only `{date, event}`.

The spine receives the facts as capped text (backend/app/services/forecast_extractor.py:3200-3203).

*Transplant (flag default off; threshold questions only).*

- (1) A deterministic join for each metric: sort actual-type rows by as_of_date (rows with value_type forecast or target are not observations) and attach the key_events that fall in each interval. One LLM call then summarizes the drivers of each interval and carries the `source_ref` ids. Values never come from the LLM.
- (2) A deterministic feature card: last value, windowed changes, range, realized volatility, slope, distance to the threshold and days left. Every window ends at or before as_of.
- (3) An anchor (persistence, consensus, a forward price, or C24's lognormal tail), adjusted by one LLM regime call into P10/P50/P90 at checkpoints taken from `build_round_periods` (backend/app/utils/sim_timeline.py:435-479).
- (4) Threshold probabilities read off those quantiles and passed in as `base_rate_anchor`.

With fewer than about 3 dated values, fall back to current behaviour.

*Evidence.* Modest: Gemini's gain over CoT was 1.2-14.7%, and Nexus lost to TimesFM at short stock horizons.

**8. Per-channel probability cards persisted in the ledger: P11 (C25, C14).**

*What Nexus does.* The synthesizer sees each draft's numbers and reasoning and must justify how it weighted them (NEX p.17-18 App. B.5). The critic sees each draft's error, so it can learn which view to trust (NEX p.17 App. B.4).

*DRF today.* The components already exist in forecast.json:

- sim shares against the research prior (backend/app/services/forecast_extractor.py:1249-1291);
- market prior and revised probability (backend/app/services/forecast_extractor.py:1803-1828);
- model vs market probability at resolution (backend/app/services/forecast_ledger.py:315-320).

But `append_forecast` persists only the scenario name, probability and criteria (backend/app/services/forecast_ledger.py:82-100), so no per-channel Brier can be computed.

*Transplant.*

- Persist `{research_prior, sim_share, market_p, quant_p, final}` for each scenario and binary.
- Compute each channel's Brier on resolved rows.
- Fuse with deterministic log-odds pooling, shrinking weights toward equal when data are thin (C25).
- Keep the spine blind to anchors until the anchoring step (C14).
- Extend the 10-pp market-divergence rule (backend/app/services/forecast_extractor.py:1831-1842) to the sim and quant channels as conflict flags.
- A Nexus-style LLM reconciler runs only as a flagged A/B test against this pooling.

**9. Dual-resolution spine over a sourced catalyst calendar: P19.**

*What Nexus does.* Dropping the macro or micro draft costs 1.3-3.6% relative MAPE (NEX p.9 Table 5). The micro agent ties each step to a scheduled catalyst (NEX p.28-29 F.10, F.13).

*DRF today.*

- Spine draws are homogeneous (the same prompt at varied temperatures) and mean-pooled (backend/app/services/forecast_extractor.py:3217-3239, 3010-3078).
- K defaults to 1 because the spread of same-model resamples is not calibrated uncertainty (backend/app/config.py:326-329). DRF_ARCHITECTURE.md:1684 still says the default is 5 (doc drift).
- `key_events` are already replayed into the sim as scheduled events (backend/app/services/simulation_config_generator.py:721-735), but they carry no source ids (deerflow_bridge/linear_research.py:473-477).

*Transplant.*

- Add `source_ref` to key_events.
- Build a catalyst calendar over (as_of, horizon], bucketed on the calendar-mode round grid (backend/app/utils/sim_timeline.py:435-479).
- Tag each catalyst as sourced or conjectured. Only sourced catalysts may move probabilities.
- Draw one outside-view spine (reference class, trend, anchors) and one catalyst-walk spine with the same scenario names, and pool them with `_pool_spine_draws`.
- Report the gap between the two drafts as a diagnostic, never as a published interval.
- Validate against K=2 homogeneous draws at matched tokens.

*Evidence.* Weak: the variants without macro or without micro keep 58-82% of the gain (§3).

**10. Hardened judge protocol: P18.**

*From Nexus.* Keep cross-family judging, randomized A/B order and strict JSON (NEX p.8 §4.4; p.19-20 App. D). Avoid showing the judge the realized events, telling it to ignore accuracy, and asymmetric verbosity between arms.

*DRF today.* `eval_forecast_quality.py` scores five prose dimensions with one configurable judge, a default of k=3 passes and a default tolerance of 0.5 (backend/scripts/eval_forecast_quality.py:1-17, 49-56).

*Transplant.*

- Assert in code that the judge's model family differs from every generator's family, using LLMMeter model ids.
- Randomize the order of pairwise version comparisons.
- Hide the outcome when judging reasoning, and normalize for length.
- Count outcome-matching claims with no source dated at or before as_of as leakage flags, not as merit.
- Keep golden Brier as the primary metric.

**11. Lessons ledger learned from errors: P16 (C03).**

*What Nexus does.* A calibration agent critiques errors (NEX p.17 App. B.4), guidelines are intersected across folds and gated on a held-out fold (NEX p.5 §3.3). The measured effect is 1.0-1.3% relative MAPE (NEX p.9 Table 5).

*DRF today.* There are no resolved production rows yet (docs/foglamp/current-shape-map.md:82). Golden rows are isolated in the evaluation ledger (backend/app/services/forecast_ledger.py:38-63, 172-178).

*Transplant (offline and default-off; build only after ranks 1, 5 and 8).*

- Critic input: the binary prompt, rationale, probability, Brier, per-component Briers (rank 8) and resolution facts. Output: one generalized rule.
- An LLM clusters rules into canonical forms, but support counting is deterministic: keep a rule only if it appears in at least m of n disjoint time windows. This replaces Nexus's unspecified free-text intersection.
- A lint rejects any rule that contains entity names, dates, numbers or outcome words from its source questions.
- Rules pass the rank-5 gate before they are injected into prompts.
- Lessons derived from golden questions never load in production.

### 5. What not to transplant, and why

- **LLM-only numeric paths with no statistical anchor** (NEX p.1 abstract). DRF needs calibrated probabilities. TimesFM beat Nexus on stocks at 6 and 13 weeks (NEX p.8 Table 3a), and the RKLB miss shows confident reasoning drifting upward (NEX p.24 Fig. 3m). Use anchor-and-adjust (rank 7).
- **An LLM synthesizer as the default fusion step.** It was never compared with averaging, because every ablation variant keeps it (NEX p.9 §4.5), and it reshapes its inputs at its own discretion, though the paper's traces describe only slight adjustments (NEX p.5 §3.3; p.28-29 F.10, F.13). It would replace auditable pooling (backend/app/services/forecast_extractor.py:3010-3078), contrary to DRF's principle of determinism wherever an LLM is not required (DRF_ARCHITECTURE.md:1742-1745).
- **Free-text guideline "intersection" and "domain-level" calibration as written** (NEX p.2; p.5 §3.3). Neither is operationalized, the gate metric is unnamed, and no guideline or acceptance rate is shown.
- **A declared cutoff plus a prompt sentence as the leakage control** (NEX p.6; p.15-18). Keep the sentence as framing only; the control must be deterministic (rank 1).
- **The Nexus judge as specified, and judge preference as evidence of quality.** It sees the outcomes and is told to ignore accuracy (NEX p.19 App. D). It gave a 97.1% win to reasoning that blames festivals for home inventory (NEX p.9 Table 4; p.27 F.6).
- **Model-invented future events as drivers** (the micro agent's `day_info`). Only sourced catalysts should move probabilities (rank 9).
- **"Exhaustive" prompting and "miss no fact" re-serialization of the timeline** (NEX p.15-18). Both are token-heavy, inflate judge scores and are unproven. DRF's per-layer budget discipline (DRF_ARCHITECTURE.md:1755-1757) favours a deterministic join plus one summarizing call.
- **The regular-grid framing with text aligned to each timestep** (NEX p.3 §2; p.6-7). DRF questions are events and thresholds over evidence dated at irregular times. Use checkpoints; do not force the evidence into a weekly series.
- **Temperature 0.1 in a single run treated as "reproducible"** (NEX p.6; p.15 App. A), and MAPE/RMSE averaged across entities of different scale as a headline metric (NEX p.7).
- **Publishing macro-vs-micro spread, or any same-model spread, as a calibrated interval.** This conflicts with the K=1 decision (backend/app/config.py:326-329).
- **A new top-level "Nexus stage".** DRF already decomposes the work more deeply (research → graph → sim → spine). The Nexus pieces belong as flag-gated sub-lanes inside REPORT and EVALUATION.

## F²Agent: Financial Fusion of Agentic Intelligence for Multimodal Trading (F2A, arXiv 2608.05668)

### 1. Essence

LLM trading agents take in several kinds of input (prices, indicators, news, sentiment) and usually combine them by pasting the numbers into the prompt as text. F²Agent argues this lets the LLM's bias toward text drown out the numeric signals, and leaves the decision exposed to whichever single source happens to be noisy (F2A p.2 §1). It makes two contributions that matter.

- **Separate channels, learned fusion.** Each data type gets its own processor. Numeric series go through small causal encoders, and LLMs are used only for text. A learned layer then combines their outputs. Besides weighting each channel for the case at hand, it adds a fixed per-channel prior: a general "how much to trust this source", kept apart from "how much to trust it here" (F2A p.5 §3.3 Eq.6).
- **Robustness rule.** During training, one channel is corrupted at random. The model is penalised if its output moves, and separately if the corrupted channel gains weight (F2A p.6 Eq.8).

DRF cannot train models and has no access to their hidden states, so the network itself does not carry over. What does carry over is a stance, rebuilt from deterministic parts:

- compute each channel's probability separately;
- learn channel reliability from resolved outcomes;
- test explicitly whether a published number depends on a single channel.

The paper's evidence for its own version is weak. On one 126-day bull-market window, its up/down accuracy is close to chance. So every transplant below is a hypothesis that DRF has to prove on its own ledger.

### 2. Method at a glance

| Component | What it does | Anchor |
|---|---|---|
| News Summarizer | Pulls Alpaca news by ticker and NYT by vector search. DeepSeek-R1 rates each article's impact; articles rated ≥5 are kept, top 3 per day, then summarised. Cached in SQLite by (date, ticker). | F2A p.22 E.1 Fig.9; p.6 §4 |
| Market / Technical agents | Causal Transformers over 30-day OHLCV and "refined alpha" windows ending at t−1. The [CLS] vector is the summary. | F2A p.17 App.D Eqs 12–14; p.22 E.2; p.24 F.1–F.2 |
| News agent | Qwen2.5-7B fine-tuned in two stages on GPT-4o-mini synthetic data. Loss is LM loss plus λ·classification CE. Output is forced to UP or DOWN; NEUTRAL is banned. | F2A p.4–5 Eq.4; p.6 §4; p.18 Eqs 17–18; p.20 Table 6 |
| Sentiment agent | R1-Distill-Llama-8B labels POSITIVE/NEGATIVE; hidden states are averaged over news items. | F2A p.3 §3.1; p.4 Eq.3; p.18 Eqs 15–16; p.21 Table 7 |
| Alignment | Last-token or [CLS] pooling, then a learned projection P_m into a shared d-dimensional space. | F2A p.5 Eq.5 |
| Adaptive modality attention | Softmax over channels with a joint query. | F2A p.5 §3.3 |
| Modality prior | r_m = u_m·A is added into keys and values. A diversity regulariser (cos² + L2) keeps the priors apart. | F2A p.5 Eq.6; p.6 Eq.7 |
| Noise-robust consistency | Perturb one random channel. Penalise ‖s(x)−s(x′)‖ plus γ·max(0, α′_m* − α_m*). | F2A p.6 Eq.8 |
| Objective | CE + λ_mod·L_mod + λ_rob·L_rob. None of the λ, γ or noise-scale values are reported. | F2A p.6 Eqs 9–10 |
| Label and backtest | UP when p_t ≥ p_{t−1}. Daily long-or-flat trading, executed at t+1, 0.3% cost, no slippage. "HOLD" is just two identical signals in a row. | F2A p.3 Eq.2; p.23 E.3 Table 8 |
| Metrics | CR (sum of log returns), ARR, SR, MDD. No calibration metric. | F2A p.24 F.3 Eqs 19–22 |

### 3. What the evidence actually shows

**Headline.** F²Agent has the best ARR on all six assets and the best SR on five: AAPL 50.08%, GOOG 120.48%, TSLA 148.41%, BTCUSD 53.57%. Its average ARR rank is 1.00, against 3.17 for FinAgent and 3.50 for buy-and-hold (F2A p.7 Table 1). The abstract's "over 20%" is the mean of the Improvement row, 20.8%. The median is 12.2% (my computation), because AAPL (48%) and AMZN (41%) carry the mean. It never has the lowest MDD on any asset; ZMR, SMA or DeepFund always do better (F2A p.7 Table 1). It also claims about 10³ LLM tokens per day, against roughly 2×10⁴ to 5×10⁴ for FinAgent, DeepFund and TradingAgents. These figures are read off a log-scale chart only (F2A p.9 §5.5 Fig.5).

**Ablations: which parts matter.** All rows except the last are single-seed, on two assets (F2A p.8 Table 2; p.7 Table 1; p.30 Table 17).

| Variant | AAPL ARR | BTC ARR |
|---|---|---|
| Concatenation fusion | 19.21 | 7.18 |
| Attention only (no prior, no regulariser) | 27.28 | 15.32 |
| Attention + prior (no regulariser) | 34.77 | 32.45 |
| Attention + regulariser (no prior) | 38.04 | 46.22 |
| Full | 50.08 | 53.57 |
| Buy-and-hold (reference) | 27.95 | 43.76 |
| Full, 3 seeds (mean ± sd) | 51.09 ± 4.09 | 50.33 ± 3.80 |

- Attention alone does not beat buy-and-hold on either asset. The gains come from the prior and the regulariser. The regulariser is the largest single component: removing it costs 15.3 pp on AAPL and 21.1 pp on BTC.
- The prior's BTC effect (7.35 pp) is less than twice the full model's seed standard deviation.
- Over three seeds, the full model beats concatenation on both assets (p = 0.038 AAPL, p = 0.016 BTC). It beats the Transformer baseline on AAPL (p = 0.015) but not significantly on BTC (p = 0.054) (F2A p.31 Table 18). This is the most robust finding in the paper.
- Direction accuracy with the fusion module is 53.6–57.9%, with MCC 0.06–0.21. Without it, MCC is about 0 (F2A p.32 Table 19). The "without fusion" variant is never defined.

**Validity threats**

- **Test-set size and regime.** There is one window, 2025-04-01 to 2025-09-30. That is 126 trading days for stocks and 183 for BTC, inferred because the accuracies equal k/126 and k/183 (F2A p.24 F.1; p.32). Five of the six assets are co-moving US mega-caps. Buy-and-hold was positive on all six, and trading is long-or-flat (F2A p.26 Table 9). On AAPL, AMZN and TSLA the F²Agent equity curve is flat (in cash) for months after its April–May gains (F2A p.25 Fig.10, my reading). The headline therefore mostly reflects sidestepping one drawdown.
- **Near-chance skill.** Per-asset accuracy is only 1.0–1.8 standard errors above 50% (my computation), so no asset is individually significant. Pooling the five stocks gives z ≈ 3.2, but only if they are treated as independent, which co-moving stocks on the same days are not. No Brier score or ECE is reported, even though the head outputs softmax probabilities (F2A p.6 Eq.9).
- **Numbers that fail their own definitions.** Reported ARR equals CR×2 for stocks and CR×252/183 for BTC. That is linear scaling, not the compounding formula of Eq.20 (F2A p.24 F.3 vs p.26 Table 9; my computation).
- **Signs of copied material.** AAPL accuracy is 50.00% with MCC 0.0051 in Table 11 but 57.94% with MCC 0.2122 in Table 19 (F2A p.27, p.32). Unexplained "PMRL_Finance" rows beat F²Agent (F2A p.26 Table 10; p.27 Tables 11–12). The figure legend reads "F³Agents" (F2A p.25 Fig.10).
- **Selective robustness evidence.** The BTC figure in the main table is the best of three seeds (F2A p.30 Table 16). LLM baselines were run at temperature 0.5 but reported as single runs (F2A p.24 F.1).
- **Adding channels does not reliably help.** On BTC only 3 of 8 channel subsets beat buy-and-hold. News alone (41.68) beats news + market (28.63). On AAPL, news + market + sentiment (24.03) is below news alone (26.61). FinAgent with news + sentiment on BTC (51.98) nearly matches F²Agent's full model. The paper does not say whether subsets were retrained or masked (F2A p.8 Table 3). The text's claim that performance "remains stable" contradicts the table (F2A p.8–9 §5.4).
- **Leakage never audited.** Backbone knowledge cutoffs are not checked. The time range of the GPT-4o-mini fine-tuning data is not stated. News timestamps relative to the market close are not specified. Eq.19 credits action_t with the t→t+1 return, while the text says execution happens at t+1 (F2A p.18 App.D; p.22 E.1; p.23 E.3; p.24 Eq.19).
- **Reproducibility and case study.** There is no code, and key hyperparameters are missing. The case study is annotated in hindsight: its "HOLD on weak cross-modal support" is an execution state, not an abstention (F2A p.9 §5.7 vs p.23 Table 8).

**What survives.** For this model, naive concatenation of channel embeddings does badly, and the robustness term plus a fixed channel prior are where the gain comes from. Everything else, including every absolute return figure, should be treated as unreliable.

### 4. Mechanisms worth transplanting to DRF, ranked

The ranking weighs what this paper uniquely contributes against its value to DRF. P02, P06 and P07 have higher stand-alone value (3), but F²Agent is only a secondary or cautionary source for them.

The build order is different, because P06 and P02 are offline preconditions for measuring anything else: P06 → P02 → P11(a) → P10 in audit mode → P11(b–c) → P07 → P11(d) only if it wins → P12 → P28.

| Rank | Candidate | F2A's role | Value / status | Token cost |
|---|---|---|---|---|
| 1 | P10 fragility gate | Origin (Eq.8) | 2 / partial | 0 (optionally 1 blind draw) |
| 2 | P11 channel cards, ledger-weighted fusion, conflict flags | Origin (Eqs 6–7) | 2 / partial | 0 (+1 blind draw) |
| 3 | P06 golden-eval rigor | Cautionary | 3 / partial | 0 |
| 4 | P07 channel value-add arms | Table 3 lesson | 3 / partial | Paid golden runs |
| 5 | P12 numeric-quantity lane | "Numbers out of prose" | 2 / absent | ≈0 |
| 6 | P02 knowledge-cutoff registry | Negative example | 3 / absent | 0 |
| 7 | P28 impact-rated triage | News Summarizer | 1 / absent | Adds cheap-tier calls |

#### 1. P10: Drop or perturb one channel as a fragility gate (extends C30)

**What F²Agent supplies.** A training-time penalty for dependence on one channel; its removal was the largest single-component drop in the paper's ablation (F2A p.6 Eq.8; p.8 Table 2). DRF cannot train, so it can only *measure* and *disclose* that dependence.

**DRF today.**
- It demotes confidence when draws disagree: spread ≥0.15 takes high to medium, ≥0.25 takes medium to low (backend/app/services/forecast_extractor.py:3072-3077).
- It flags ensemble spread above 0.15 (backend/app/services/ensemble.py:261-265, 341-344).
- Neither fires under the defaults: K=1 (backend/app/config.py:326-329), and `FORECAST_ENSEMBLE_MODELS` is empty, so no second model is pooled (backend/app/config.py:638-643).
- The live second channels are:
  - the market, which can move a binary through the 10 pp restatement and stamps prior and revised values (backend/app/services/forecast_extractor.py:1803-1828, 1831-1914);
  - the scenario partition, which overrides a binary and keeps `pre_reconciliation_probability` (backend/app/services/forecast_extractor.py:2443-2447).

**Transplant.** Add a pure pass after `_reconcile_forecast_contract` (backend/app/services/report_agent.py:3098) and before the publish gate. It rebuilds each binary's drop-one counterfactuals from values DRF already records:
- the market-removed value is `market_influence.prior_probability`;
- the partition-removed value is `pre_reconciliation_probability`;
- when the ensemble is on, drop one ensemble member at a time and re-pool.

It records `max_swing`, the channel that dominates, and whether the forecast flips across 0.5. When the swing is ≥0.15 or there is a flip, it:
- attaches an interval (binaries carry none today);
- tags that interval with its provenance, following the `interval_source` convention in backend/app/services/forecast_extractor.py:3084-3146;
- demotes confidence one level;
- publishes a "fragile: depends on X" note.

With only one channel it reports "not assessable" and never invents a value.

**Needs P11 first.** Perturbation, the operation the paper actually uses, only works once fusion is a formula (P11 step d). The market's noise band can then come from snapshot fields: bid, ask, one-day change and liquidity (backend/app/utils/prediction_markets.py:521-545). Those fields are not copied into the anchor today (backend/app/services/forecast_extractor.py:1683-1732).

**Hinge analog.** Add a unit-tested invariant: a channel that fails a quality check can never gain weight or narrow an interval. Failures include a loose match, match_confidence <0.6, a non-converged simulation or a stale snapshot.

**Validation.** Start in record-only mode. Enforce only if binaries flagged as fragile score worse Brier than robust ones, with a question-clustered bootstrap CI (P06). Widening an interval leaves point Brier unchanged, so the flag has to earn its place by being informative.

#### 2. P11: Per-channel cards, ledger-weighted log-odds fusion and conflict flags (extends C25, C14)

**What F²Agent supplies.** A fixed per-channel prior on top of case-by-case weighting (F2A p.5 Eq.6). A penalty on redundant priors (F2A p.6 Eq.7). And its own ablation's warning that case-by-case weighting alone does not beat buy-and-hold (F2A p.8 Table 2; p.7 Table 1).

**(a) Cards, observability only.** Persist a card per channel for each binary: research, market, partition, ensemble members, and the simulation share as a diagnostic. Each card carries its quality metadata. Resolved rows already store `model_p` and `market_p_at_research` (backend/app/services/forecast_ledger.py:369-399, written at backend/scripts/resolution_monitor.py:558-570). `market_brier_summary` should add the market's own Brier and the paired model-minus-market delta; today it scores only the model (backend/app/services/forecast_ledger.py:423-436). That gives the first data for fitting the channel prior at no cost.

**(b) Independence.** Both the scenario spine and the binary prompts already see the market pack (backend/app/services/forecast_extractor.py:3194-3199, 2706-2717). Today's "research" probability is therefore already anchored to the market, and pooling it with the market would count the market twice. A market-blind research card needs the C14 separation: one extra draw that does not see the market, behind a flag. Simulation personas are built from the same research dossier, so the simulation card needs a correlation discount. That is the diversity-regulariser idea (F2A p.6 Eq.7) used as a weight penalty rather than a training loss.

**(c) Conflict flags.** Extend the >10 pp market-divergence rule (backend/app/services/forecast_extractor.py:1856) to any pair of cards. Stamp `cross_channel_conflict`, require the rationale to address the dissenting channel, and leave the probability unchanged.

**(d) Fusion, off by default.**
- fused logit = Σ_c w_c·logit(p_c), with w = softmax(b_c + q_c). This is a weighted version of `_extremized_logodds` (backend/app/services/ensemble.py:118-136).
- b_c is each channel's reliability, fitted from its Brier score on production rows only (`is_production_calibration_row`, backend/app/services/forecast_ledger.py:49-63).
- When data is thin, b_c falls back to equal weights. This mirrors `fit_recalibrator`, which returns identity below 10 points (backend/app/services/backtest.py:215-216). My suggestion is a stricter bar: at least 30 resolved binaries per channel, and a bootstrap CI on the Brier gap that excludes 0.
- q_c must be monotone in observable quality: match equivalence and confidence, liquidity and spread, draw spread.

**Policy constraints.** This fusion is a forecasting policy, like extremize > 1, which DRF reserves for the WP14 outcome-blind promotion gate (backend/app/config.py:330-333). The simulation card cannot enter fusion while `SIMULATION_FORECAST_EFFECT=diagnostic_only` (backend/app/config.py:1475-1488; backend/app/services/decision_channel.py:747).

#### 3. P06: Golden-eval statistical rigor and result-integrity checks (extends C40)

**DRF today.** `score_pairs` reports mean Brier, log score, accuracy, ECE and breakdowns. It has no CI, no skill score and no paired comparison (backend/scripts/golden_eval.py:147-182). The documented workflow is to diff `eval_report.json` across versions by eye (backend/scripts/golden_eval.py:19-30). The golden set has 30 questions, 24 of them YES (counted from backend/tests/eval/golden_questions.json). A constant 0.8 forecast therefore scores Brier 0.16, so a skill score against climatology is mandatory.

**What F²Agent's failures add**
- A deterministic lint that recomputes every headline number from per-item rows. This catches failures like F²Agent's own: ARR that does not follow its Eq.20 (F2A p.24 vs p.26), and Table 11 contradicting Table 19.
- Spread reported for both arms, never only the new one (F2A p.24 F.1).
- A ban on headlining the best run (F2A p.30 Table 16).
- Gain concentration: the share of the improvement that comes from the top-k questions (F2A p.25 Fig.10).
- MCC and the predicted-YES rate.
- A question-clustered paired bootstrap instead of t-tests over 3 seeds (F2A p.31 Table 18).

#### 4. P07: Per-model stage and channel value-add arms, with an A/A noise floor (extends C30)

**What F²Agent supplies.** A channel-subset grid, and proof of why it is needed: adding channels is not monotone and the paper's text misstates the result (F2A p.8 Table 3).

**DRF arms.** Run each arm per serving model:
- research only;
- + market;
- + quant card (P12);
- + simulation (diagnostic).

Add an A/A duplicate to measure the noise floor, run at least 3 seeds per arm, and replay a frozen search and fetch snapshot so web drift does not confound the result. State the subset semantics (masked or re-derived), which the paper leaves unstated. A channel becomes default-on only if it beats research-only by more than the A/A floor. The cheap report-layer version is exactly P10's counterfactual machinery, so the two should share code.

#### 5. P12: Numeric-quantity lane with a deterministic feature card (extends C24)

**What F²Agent supplies.** Numbers go through structured processing and LLM tokens are spent only on text (F2A p.9 §5.5). Every window ends before the prediction date (F2A p.17 Eqs 12–14).

**DRF today.**
- quantitative.json reaches prompts as a rendered markdown table (backend/app/services/report_agent.py:2034-2062, 1873-1887).
- The spine accepts `quantitative_facts` (backend/app/services/forecast_extractor.py:3149-3154, 3200-3203), but the call site never passes it (backend/app/services/report_agent.py:2895-2903).

**Transplant.** For any numeric target behind a threshold binary, compute a feature card in code:
- last value and its as-of date;
- changes over fixed windows;
- realised volatility and trend slope;
- distance to the threshold in volatility units;
- time remaining.

Every window must end at or before as_of. Pass the card as a compact structured block, and use C24's lognormal tail as `base_rate_anchor` when a price series exists. With fewer than 3 dated values, skip the card and leave current behaviour unchanged.

**Evidence.** F²Agent has no ablation that isolates this. Adding numeric encoders helped AAPL by +20.7 pp and hurt BTC by 13–20 pp (F2A p.8 Table 3). Validate it through P07.

#### 6. P02: Model knowledge-cutoff registry, with headline scores from post-cutoff questions only

F²Agent's only guard against backbone-knowledge leakage is a late test window. It never states model cutoffs or when its synthetic training data and its news were dated (F2A p.18 App.D; p.22 E.1; p.24 F.1).

DRF's golden questions resolve between 2024-01-10 and 2025-02-09 (counted). That is probably inside current backbones' training data, so the evaluation Brier mixes memory of the answer with forecasting skill. No cutoff handling exists in backend/app or backend/scripts.

**Transplant.**
- Keep a registry of {model_id: cutoff}.
- Headline metrics come only from questions that resolve after the cutoff plus a buffer, for every model that touched the run.
- Earlier rows are tagged `characterization_only`, which `is_production_calibration_row` already excludes (backend/app/services/forecast_ledger.py:49-63).
- An unknown cutoff means no headline number.

#### 7. P28: Impact-rated source triage per KIQ, failing open (extends C36)

**What F²Agent supplies.** An LLM impact rating with a threshold and a top-3 cut (F2A p.22 E.1 Fig.9). It was never ablated.

**DRF hook.** Seed rows are sorted by source tier and cut to 6 per KIQ, the key intelligence questions that research is organised around (deerflow_bridge/linear_research.py:105-106, 4604-4614).

**Transplant.** A cheap-tier impact score per (KIQ, source) reorders the rows before that cut and is kept in provenance. If rating fails, fall back to tier order. Use a k far looser than 3.

**Caveat.** Research is DRF's dominant token cost, so this has to be measured on tokens saved and golden Brier before adoption. The paper's (date, ticker) cache duplicates what deerflow_bridge/cached_fetch.py and search_tools.py already do.

### 5. What not to transplant, and why

- **The learned fusion network, LLM hidden-state embeddings and per-channel projections** (F2A p.5 Eq.5; F2A:method:5, F2A:evidence:10). These need hidden states and labelled training data for each question; DRF has neither. And case-by-case attention alone was no better than buy-and-hold even in the paper (F2A p.8 Table 2; p.7 Table 1).
- **Two-stage fine-tuning on GPT-4o-mini synthetic data plus a classification loss** (F2A p.18 Eq.18; F2A:method:6). DRF does not train models. Building examples from golden questions would leak answers into the isolated evaluation ledger. The paper gives no base-versus-fine-tuned comparison.
- **Forced UP/DOWN with NEUTRAL banned** (F2A p.20 Table 6; F2A:method:4). This conflicts with calibrated probabilities. The confidence output claimed in Eq.17 is never even asked for in the prompt. DRF's anti-hedging need is C20's job, and C20's rule is symmetric.
- **The backtest, execution rules and ARR/SR/MDD metrics** (F2A p.23–24; F2A:method:11). These serve a trading objective. The one reusable rule, that a signal dated t uses only data up to t, belongs to P01's point-in-time gates.
- **The diversity regulariser as a loss** (F2A p.6 Eq.7). Only its idea, discounting redundant channels, survives, inside P11.
- **Attention weights as explanations** (F2A p.31–32 Figs 11–12). Their faithfulness is never tested. DRF should publish only weights that *are* the fusion formula, never an LLM's story about which channel drove the result.
- **"Cross-modal HOLD" presented as abstention** (F2A p.9 §5.7). It is two identical signals in a row (F2A p.23 Table 8), not a mechanism.
- **A hard top-3-per-day evidence cap** (F2A p.22). It would starve DRF's open-ended, multi-actor questions.
- **The per-item sentiment agent** (F2A:evidence:8). Its marginal value flips sign across channel subsets (F2A p.8 Table 3). A stance tally is at most an optional P11 card.
- **More LLM "specialist agents".** F²Agent's token savings come from *not* using LLMs on numbers (F2A p.9 §5.5), not from splitting work across roles. DRF should not add LLM roles in its name.

## Implementation roadmap

### Executive summary

This program lands 81 work packages (WPs), built from transplant candidates found in FinanceHarness, StockAgent and TradingAgents plus DRF's own audits. The work runs in 15 waves after a wave-0 sync with `main`. Another 19 WPs are deferred, with the verifier-grounded reason recorded for each.

The highest-leverage changes, in plain language:

1. **Make the track record real and scoreable** (EVAL-1, EVAL-2, EVAL-3, EVAL-4, EVAL-13).
   - **Unpublishable and repeated rows:** today a forecast is appended to the scored ledger before the final publication audit. At most 5 of 29 live rows are actually publishable, and some repeat 7x or 5x.
   - **No resolved targets:** nothing ever resolves a target, so historical calibration stays at n=0 forever.
   - **What the program does:**
     - Commit the exact published bytes, once.
     - Settle markets deterministically with honest "known-at" times.
     - Add a manual settlement path; only 1 of 344 stored binaries has an exact market anchor, so this is the only realistic label source.
     - Keep evaluation runs out of production calibration.
2. **Stop time leaks** (TIME-1, TIME-3, TIME-6, TIME-7, TIME-8, TIME-9, TIME-2).
   - **Overwritten as-of date:** the v3 research engine lets the model overwrite the run's as-of date. MiniMax once reported its training cutoff, and that date then anchors the graph and the simulation calendar.
   - **Expired markets:** they can anchor binaries and seed simulation priors.
   - **Unsafe hindcasts:** a hindcast would requote live odds.
   - **What the program does:**
     - Pin the as-of date.
     - Gate markets by end date.
     - Build an honest, opt-in hindcast lane with point-in-time evidence gates.
     - Capture source publication dates.
3. **Make every number in the report traceable** (RESEARCH-4, REPORT-7, REPORT-8, REPORT-9, RESEARCH-7, RESEARCH-9).
   - **Mistyped dates:** 14 of 57 quantitative rows in a live run put forecast target dates into `as_of_date`.
   - **True citations stripped:** 33 of 43 fetched values sit beyond the 1,200-character excerpt the report checks, so true citations get stripped.
   - **Silent citation surgery:** 55-94% of report markers are stripped, and the final audit shows a clean document.
   - **What the program does:**
     - Type and verify rows once.
     - Carry evidence windows.
     - Show a labelled verified-figures block.
     - Record the citation surgery.
4. **Probability honesty in the report** (REPORT-1, REPORT-2, REPORT-3, REPORT-4, REPORT-10).
   - **Laundered values:** malformed probabilities become uniform splits or 0.98.
   - **Stale published headlines:** report_ffe1ea6bf50d was published with a headline saying 40% while the forecast said 35%.
   - **Unmarked absence:** absent inputs read like empty findings.
   - **Duplicated market table:** the binary draw sees a stale second copy of the market table.
5. **Simulation honesty** (SIM-1, SIM-2, SIM-5, SIM-6).
   - **Missing verdict:** default calendar runs never carry a validity verdict, so the report's "inconclusive" warning can never fire.
   - **Invalid votes:** hallucinated agent ids vote.
   - **Misattributed events:** research timeline events are counted as a real actor's behaviour.
   - **Stale world clock:** agents are told "(first period)" after failed steps.
6. **Infrastructure correctness** (INFRA-1, INFRA-2, INFRA-10, INFRA-12, EVAL-10).
   - **Usage misattributed:** usage is attributed to the wrong call under concurrency.
   - **Bad replies cached:** truncated or filtered replies are cached forever.
   - **Path traversal:** URL ids are joined into paths, including one `rmtree`.
   - **Leaky tests:** the test suite reads the developer's shell environment.
   - **Collapsed samples:** the LLM cache collapses replicate and control calls.

**Defaults.** Everything new sits behind a `Config` knob with a comment and a documented `.env.example` entry. With a knob off, output is byte-identical to today. Honesty checks fail closed. Probability-moving policies default off until a WP14 outcome-blind promotion (ADR 0002 I-21): the REPORT-11 guard, the REPORT-12 blend, the REPORT-13 counter-case, the RESEARCH-13 packer and EVAL-14 targets.

**Why 15 waves.** `report_agent.py` (13.5k lines) is edited by 29 WPs. The rule of at most two WPs per big file per wave therefore needs ceil(29/2) = 15 waves on its own. Architect re-scoping already removed six `report_agent.py` edits. The plan front-loads foundations: waves 1-7 carry 46 WPs, and the report-heavy tail is thinner.

### Integration rules

**Wave 0.**
1. Merge `main@1e40844` into `feat/finharness-transplants`. Main now includes 2201225 (settings endpoint fix), c25f337 (SIM-REACT reaction phase, +804 lines in `run_parallel_simulation.py`) and 1e40844.
2. Run the full offline suite and record the baseline count.
3. All anchors in `run_parallel_simulation.py`, `actors.py`, `simulation_config_generator.py` and `settings.py` refer to `main@1e40844`.

**Per wave.**
1. Each WP branch is cut from the integration branch at the start of its wave.
2. Branches are merged in the listed order.
3. After the wave, run the full suite (`DRF_TEST_PROCESS=1`), `ruff`, `check_env_drift.py --strict` and `compileall`.
4. A red gate blocks the next wave.

**Registries.** These are treated like `config.py`: conflicts from adjacent insertions are resolved by keeping both lines.
- `config.py`
- `.env.example`
- The research-child forwarding tuples `RESEARCH_CHILD_KNOBS` and `RESEARCH_CHILD_V3_KNOBS`, created by TIME-1
- `_DEPLOYED_BRIDGE_MODULES` and the `setup.sh` module loop
- Keys added to `capture_safety_policy_v1`

**Knob conventions.**
- Backend knobs use `os.environ.get('X','d').strip().lower() == 'true'`.
- The bridge uses `_env_flag`.
- Forwarded booleans are `'true'`/`'false'`.

**Single owners of shared helpers.**

| Helper | Owner (wave) | Reused by |
|---|---|---|
| `utils/canonical_json.py`, `utils/point_in_time.py`, `ledger_commit.run_post_publication` | EVAL-1 (1) | Backend WPs, TIME-7, EVAL-2, EVAL-13, EVAL-19 |
| `_env_flag`, the quant `verification` enum, `classify_quant_row` | RESEARCH-4 (1) | TIME-1, TIME-4, TIME-9, REPORT-7, REPORT-8, RESEARCH-5 |
| `_routing_pinned()` | EVAL-10 (2) | INFRA-2, INFRA-6, INFRA-8 |
| `parse_market_end` | TIME-3 (2) | EVAL-2, EVAL-3, EVAL-19 |
| `_merge_supports` | REPORT-7 (3) | RESEARCH-7 |
| Evaluation context | EVAL-13 (3) | TIME-6, TIME-7 |
| `absence.market_status` | REPORT-4 (4) | RESEARCH-3 |
| `build_spine_user_prompt` | EVAL-11 (6) | RESEARCH-12, RESEARCH-13 |
| `FakeLLMClient` | INFRA-12 (1) | All tests |

**Forbidden names.** No new ledgers (ADR 0002 alternative 6). No `app/evaluation/`, `app/services/resolution_service.py` or `app/services/forecast_evidence_pack.py`. No `quantitative_facts=` or `base_distribution=` in `_derive_and_pin_forecast_spine`. The WP4/6/13/14 characterization tests pin all of these.

### Master table

| WP | Title | Candidates | Area | Value / effort | Wave | Status |
|---|---|---|---|---|---|---|
| EVAL-1 | Sealed, idempotent forecast-ledger commits after the final audit | C19 (+C03 target capture) | EVAL | 3 / L | 1 | implement-now |
| EVAL-2 | Market settlement events v2 (publishable-at-issue, eligibility, outcome_known_at, 50/50 ambiguity) | C03 (+P17) | EVAL | 4 / L | 3 | implement-now |
| EVAL-3 | Settlement fold + point-in-time admissible() gate | C03 cont. (+P04, P17 fold-ins) | EVAL | 4 / M | 4 | implement-now |
| EVAL-4 | Manual settlement path (resolve CLI, v1_resolve hardening, corrections) | C03 cont. | EVAL | 4 / M | 6 | implement-now |
| EVAL-5 | Market-relative skill scorer | N01 (+P06 item) | EVAL | 3 / M | 12 | implement-now |
| EVAL-6 | Market price-time provenance on anchors | P05 | EVAL | 3 / S | 7 | implement-now |
| EVAL-7 | golden_eval honesty layer (eval_stats, rigor block, duplicate ids, atomic writes) | P06 (+C40 hardening) | EVAL | 3 / M | 1 | implement-now |
| EVAL-8 | Golden headline tiering (prospective vs hindcast) | P02 | EVAL | 3 / S | 9 | implement-now |
| EVAL-9 | Golden set v2 data contract (outcome-free criteria, leak lint) | P17 (+C21, P03 hygiene) | EVAL | 3 / M | 2 | implement-now |
| EVAL-10 | LLMClient isolation + binary_quality clobber fix + judge hygiene | shared prerequisite (P15/P03/P07; P18 slice) | EVAL | prereq / S | 2 | implement-now |
| EVAL-11 | Shadow spine cross-backbone sensitivity check | P15 | EVAL | 3 / M | 6 | implement-now |
| EVAL-12 | Golden contamination probes (closed-book, recall) | P03 | EVAL | 3 / M | 14 | implement-now |
| EVAL-13 | Evaluation-run admission pin, ledger routing, monitor exclusion, target binding | C40 | EVAL | 3 / L | 3 | implement-now |
| EVAL-14 | Structured numeric targets on binaries + ladder audit + scoring core | P14 | EVAL | 3 / M | 13 | implement-now |
| EVAL-15 | Per-stage scorecard sidecar + score CLI + env pins | P22 | EVAL | 3 / M | 3 | implement-now |
| EVAL-16 | Tool-call counters + cross-run scorecard aggregate | P22 cont. | EVAL | 3 / S | 12 | implement-now |
| EVAL-17 | Metering fidelity (seed sims, resume-safe totals, cache-read split) | P20 | EVAL | 3 / M | 5 | implement-now |
| EVAL-18 | Cost card + config fingerprint + ledger config_hash | P20 cont. | EVAL | 3 / M | 8 | implement-now |
| EVAL-19 | Frozen evaluation bundle (capture, backfill, integrity) | P07 prerequisite | EVAL | 3 / M | 12 | implement-now |
| EVAL-20 | Label-free block-movement study with A/A noise floor | P07 | EVAL | 3 / L | 15 | implement-now |
| EVAL-21 | Masked (pseudonymized) replay | C21 | EVAL | 2 / L | - | deferred |
| EVAL-22 | Held-out recalibration promotion + frozen snapshots | P04 | EVAL | 2 / L | - | deferred |
| EVAL-23 | Error-grounded lessons ledger | P16 | EVAL | 1 / XL | - | deferred |
| EVAL-24 | Two-tier rubric and hardened judge protocol | P18 | EVAL | 2 / L | - | deferred |
| TIME-1 | Pin v3 actors.json as_of to the plan as-of (+ env-forwarding registry) | C08 split | TIME | honesty fix (C08 4) / S | 2 | implement-now |
| TIME-2 | Capture source publication dates in v3 | C18 | TIME | 4 / M | 5 | implement-now |
| TIME-3 | Polymarket endDate hygiene | C35 | TIME | 3 / S | 2 | implement-now |
| TIME-4 | Restore v3 quantitative sanity parity | P13 split | TIME | parity fix (P13 3) / S | 9 | implement-now |
| TIME-5 | Shadow numeric-coherence guard for binary thresholds | P13 | TIME | 3 / M | 9 | implement-now |
| TIME-6 | Hindcast policy pin + market withholding (re-scoped) | C08 split (+C35 withhold) | TIME | C08 4 / S-M | 5 | implement-now |
| TIME-7 | Hindcast admission + v3 as-of injection | C08 | TIME | 4 / M | 6 | implement-now |
| TIME-8 | Point-in-time evidence gates for hindcast research | P01 | TIME | 3 / L | 7 | implement-now |
| TIME-9 | PIT citation wall, research audit, integrity verdict | P01 cont. | TIME | 3 / M | 8 | implement-now |
| TIME-10 | Official-data vendor core + FRED/ALFRED vintages | C06 | TIME | 3 / M | 10 | implement-now |
| TIME-11 | SEC EDGAR as-filed statements | C06 cont. | TIME | 3 / M | 11 | implement-now |
| TIME-12 | Research gateway plumbing for data tools | C06 cont. | TIME | 3 / M | 11 | implement-now |
| TIME-13 | v3 engine integration of data tools | C06 cont. | TIME | 3 / L | 14 | implement-now |
| TIME-14 | Market-threshold reference-class tools + numeric-quantity lane | C24, P12 | TIME | 2 / XL | - | deferred |
| RESEARCH-1 | Fetch shell classifier, provenance wall, hard fetch bound | C17 | RESEARCH | 3 / M | 1 | implement-now |
| RESEARCH-2 | Typed source outcomes, refusal latch, research health stage | C05 | RESEARCH | 3 / M | 2 | implement-now |
| RESEARCH-3 | Absence-of-evidence discipline (re-scoped, no report edit) | C12 | RESEARCH | 3 / S | 6 | implement-now |
| RESEARCH-4 | Quant-row typing + the single page-verification step | C27 (+C07 P0, C32 A2) | RESEARCH | 4 / M | 1 | implement-now |
| RESEARCH-5 | quant_typing module, persona qualifier, projection lint (re-scoped) | P25 | RESEARCH | 3 / M | 7 | implement-now |
| RESEARCH-6 | Forecaster attribution + dispersion diagnostics (shadow) | N03 | RESEARCH | 3 / M | 11 | implement-now |
| RESEARCH-7 | Verbatim evidence-span contract (audit-first) | C32 | RESEARCH | 4 / M | 4 | implement-now |
| RESEARCH-8 | Declarative DERIVED findings | C07 | RESEARCH | 3 / M | 15 | implement-now |
| RESEARCH-9 | Citation-surgery telemetry | C33 | RESEARCH | 3 (core 4) / M | 10 | implement-now |
| RESEARCH-10 | Evidence count headers + fair digest truncation | C36 (+P28 salvage) | RESEARCH | 3 / S | 13 | implement-now |
| RESEARCH-11 | Question spec producer (+ v3 forecast-inputs parity) | C02 (+P31 rule; REPORT-17 kernel) | RESEARCH | 4 / M | 4 | implement-now |
| RESEARCH-12 | Question spec consumers (sim horizon, spine block, disclosure) | C02 cont. | RESEARCH | 4 / S | 8 | implement-now |
| RESEARCH-13 | Forecast-prompt context packer | P09 | RESEARCH | 4 / M | 7 | implement-now |
| RESEARCH-14 | In-loop context compaction + error-classified recovery | C28, P29 | RESEARCH | 2 / S | - | deferred |
| RESEARCH-15 | Tool/skill catalog discipline + numeric recipe skill | C45, P30 | RESEARCH | 2 / S | - | deferred |
| RESEARCH-16 | Search pre-flight with cache warming | P24 | RESEARCH | 2 / S | - | deferred |
| RESEARCH-17 | Impact-rated per-KIQ source triage | P28 | RESEARCH | 1 / S | - | deferred |
| RESEARCH-18 | Standalone default-assumption scoping | P31 | RESEARCH | 2 / S | - | deferred |
| REPORT-1 | Honest probability parsing + needs_review state | C01 | REPORT | 3 / M | 1 | implement-now |
| REPORT-2 | Deterministic narrative sync after probability moves | P08 | REPORT | 3 / M | 2 | implement-now |
| REPORT-3 | Alias-aware slot audit (observe) + slot repair | P08 cont. | REPORT | 3 / M | 11 | implement-now |
| REPORT-4 | Typed absence markers in report prompts + market status | C04 | REPORT | 3 / M | 4 | implement-now |
| REPORT-5 | Fail-closed hollow/errored-simulation gate on the signal pack | C04 split | REPORT | 3 / S | 6 | implement-now |
| REPORT-6 | Simulation world clock absence states | C04 split | REPORT | 3 / S | 4 | implement-now |
| REPORT-7 | Research-side evidence windows + verified_facts.json | C11 | REPORT | 4 / M | 3 | implement-now |
| REPORT-8 | Labelled verified-figures block + Part-2 injection | C11 cont. | REPORT | 4 / M | 8 | implement-now |
| REPORT-9 | Shadow verified-figure check + provenance sidecar | C11 cont. | REPORT | 4 / M | 12 | implement-now |
| REPORT-10 | Information-wall tests, dossier market de-dup, honest labels | C14 | REPORT | 4 / M | 5 | implement-now |
| REPORT-11 | Probability-shape telemetry, objective_signals, symmetric guard (off) | C20 | REPORT | 3 / M | 10 | implement-now |
| REPORT-12 | Deterministic market-blend arithmetic (off) | C25 | REPORT | 3 / S | 13 | implement-now |
| REPORT-13 | Evidence-cited counter-case pass (off) | C09 | REPORT | 3 / M | 14 | implement-now |
| REPORT-14 | Verbal-probability lexicon + evidence state | N02 | REPORT | 2 / S | - | deferred |
| REPORT-15 | Drop/perturb-one-channel fragility gate | P10 | REPORT | 2 / M | - | deferred |
| REPORT-16 | Per-channel probability cards + log-odds fusion | P11 | REPORT | 2 / M | - | deferred |
| REPORT-17 | Dual-resolution spine drafts over a catalyst calendar | P19 | REPORT | 2 / M | - | deferred |
| REPORT-18 | Graph situation mining with per-actor budget | P27 | REPORT | 2 / L | - | deferred |
| SIM-1 | Shared decision-channel validity verdict | P26 (+P21 coverage) | SIM | 3 / M | 2 | implement-now |
| SIM-2 | Roster-bound decision validation + reason-coded accounting | C26 (+C31a, C16a) | SIM | 3 / M | 3 | implement-now |
| SIM-3 | Run-artifact hygiene (schedule audit, digest rotation, organic leak) | C16 | SIM | 3 / S | 9 | implement-now |
| SIM-4 | Zero-LLM prior-echo diagnostic | C30 | SIM | 3 / S | 14 | implement-now |
| SIM-5 | Scheduled-event provenance | C42 | SIM | 3 / M | 4 | implement-now |
| SIM-6 | Truthful per-period context delivery | P23 (+C42 item b) | SIM | 3 / M | 5 | implement-now |
| SIM-7 | Human-authored outcome_power overrides in overlays | C31 | SIM | 3 / S | 13 | implement-now |
| SIM-8 | Decision elicitor sees the period's scheduled events | P23 cont. | SIM | 3 / S | 10 | implement-now |
| SIM-9 | Intra-sim LMSR belief market | C48 | SIM | 2 / L | - | deferred |
| SIM-10 | Output-side population diagnostics | P21 | SIM | 2 / M | - | deferred |
| INFRA-1 | LLM transport normalization | C41 | INFRA | >=3 / M | 1 | implement-now |
| INFRA-2 | Structured-output repair turn + cache discard | C10 | INFRA | >=3 / M | 3 | implement-now |
| INFRA-3 | max_tokens escalation + fail-closed truncated JSON | C15 | INFRA | >=3 / M | 11 | implement-now |
| INFRA-4 | Non-finite guards + status-first error classification | C44 | INFRA | >=3 / M | 12 | implement-now |
| INFRA-5 | Report tool-call boundary | C34 | INFRA | >=3 / M | 9 | implement-now |
| INFRA-6 | Single provider request-override helper | C23 | INFRA | >=3 / S | 7 | implement-now |
| INFRA-7 | Run-shape pin, drift detection, resume lineage | C29 | INFRA | >=3 / M | 4 | implement-now |
| INFRA-8 | Model provenance (requested vs served) | C43 | INFRA | >=3 / M | 8 | implement-now |
| INFRA-9 | ContextVar propagation + fork safety-policy inheritance | C39 | INFRA | >=3 / S | 5 | implement-now |
| INFRA-10 | Identifier containment + local API hardening | C38 | INFRA | >=3 / M | 1 | implement-now |
| INFRA-11 | Stable actor identity for non-Latin names | C37 | INFRA | >=3 / S | 10 | implement-now |
| INFRA-12 | Hermetic test harness (+ declare undeclared deps) | C22 (+C47 item 1) | INFRA | >=3 / M | 1 | implement-now |
| INFRA-13 | Import fences (AST egress policy) | N04 | INFRA | >=3 / S | 6 | implement-now |
| INFRA-14 | Config audit (strict parsing, ghost knobs, run options) | C13 | INFRA | >=3 / M | 7 | implement-now |
| INFRA-15 | Live research/report progress event stream | C46 | INFRA | 2 / S | - | deferred |
| INFRA-16 | Packaging and install hygiene | C47 | INFRA | 2 / S | - | deferred |

### Waves

**Wave 0: sync.**
- Merge `main@1e40844` and re-baseline the suite.
- No WP starts before this, because the SIM WPs and INFRA-6 depend on main's changes.

**Wave 1: foundations (8).**
- **WPs, in merge order:** INFRA-12, INFRA-10, INFRA-1, EVAL-1, EVAL-7, REPORT-1, RESEARCH-4, RESEARCH-1.
- **INFRA-12:** hermetic tests land first, so every later WP's tests run without ambient env or egress. It also declares networkx and mcp before CI moves to the lockfile.
- **INFRA-10:** security containment, shipped unflagged.
- **INFRA-1:** normalizes every completion (finish reasons, empty and filtered replies, per-call usage).
- **EVAL-1:** creates the sealed ledger commit, canonical JSON and the as-of validator used by more than ten WPs.
- **EVAL-7:** gives golden_eval honest statistics.
- **REPORT-1:** stops probability laundering.
- **RESEARCH-4:** types quant rows and becomes the single page-verification step.
- **RESEARCH-1:** stops extraction shells counting as fetched pages.
- **report_agent.py:** EVAL-1 and INFRA-10.

**Wave 2: pins and isolation (7).**
- **WPs, in merge order:** TIME-1, EVAL-10, TIME-3, SIM-1, EVAL-9, REPORT-2, RESEARCH-2.
- **TIME-1:** fixes the live as-of override and creates the env-forwarding registry.
- **EVAL-10:** isolates LLM clients (cache bypass, pinned model, correct tier routing) and fixes the binary_quality clobber.
- **TIME-3:** stops expired markets anchoring binaries.
- **SIM-1:** gives default calendar runs a real validity verdict.
- **EVAL-9:** makes golden criteria outcome-free.
- **REPORT-2:** keeps headlines consistent with the probabilities.
- **RESEARCH-2:** types source failures honestly.

**Wave 3: containment and evidence (6).**
- **WPs, in merge order:** EVAL-13, EVAL-2, INFRA-2, REPORT-7, SIM-2, EVAL-15.
- **EVAL-13:** creates the single evaluation-run containment and starts the hindcast critical path.
- **EVAL-2:** writes deterministic settlement events.
- **INFRA-2:** adds a real JSON repair turn and discards failed cached attempts.
- **REPORT-7:** carries evidence windows past the 1,200-character excerpt.
- **SIM-2:** makes the roster bind decisions.
- **EVAL-15:** adds the per-stage scorecard.

**Wave 4: fold, absence, question spec, provenance (7).**
- **WPs, in merge order:** INFRA-7, EVAL-3, REPORT-4, RESEARCH-11, RESEARCH-7, SIM-5, REPORT-6.
- **INFRA-7:** adds the run-shape pin and resume lineage.
- **EVAL-3:** adds the as-of calibration gate.
- **REPORT-4:** adds typed absence markers and market status.
- **RESEARCH-11:** adds the question spec and v3 forecast-inputs parity.
- **RESEARCH-7:** makes verbatim spans audit-first.
- **SIM-5:** injected events stop posing as actor behaviour.
- **REPORT-6:** the world clock stops saying "(first period)" after failures.

**Wave 5: hindcast policy and walls (6).**
- **WPs, in merge order:** INFRA-9, EVAL-17, TIME-6, REPORT-10, TIME-2, SIM-6.
- **INFRA-9 and EVAL-17:** fix usage attribution and metering.
- **TIME-6:** hindcast market withholding.
- **REPORT-10:** pins the information walls and removes the duplicated market table.
- **TIME-2:** records source dates.
- **SIM-6:** delivers truthful period context.

**Wave 6: admission and gates (6).**
- **WPs, in merge order:** TIME-7, EVAL-11, REPORT-5, RESEARCH-3, EVAL-4, INFRA-13.
- **TIME-7:** validated as_of, fail-closed and v3-only.
- **EVAL-11:** extracts the spine prompt builder and adds the shadow backbone check.
- **REPORT-5:** hollow simulations stop feeding the report.
- **RESEARCH-3:** absence discipline.
- **EVAL-4:** manual settlement.
- **INFRA-13:** import fences.

**Wave 7: point-in-time and packer (6).**
- **WPs, in merge order:** INFRA-14, INFRA-6, TIME-8, EVAL-6, RESEARCH-5, RESEARCH-13.
- **INFRA-14:** config audit and the single Config parser.
- **INFRA-6:** provider overrides.
- **TIME-8:** PIT gates.
- **EVAL-6:** price-time stamps.
- **RESEARCH-5:** the quant_typing module.
- **RESEARCH-13:** the section-aware forecast context packer, default off.

**Wave 8: citation wall and figures (5).**
- **WPs, in merge order:** INFRA-8, EVAL-18, TIME-9, REPORT-8, RESEARCH-12.
- **INFRA-8:** model provenance.
- **EVAL-18:** cost card.
- **TIME-9:** PIT citation wall and integrity verdict.
- **REPORT-8:** the labelled verified-figures block replaces the key-metrics table.
- **RESEARCH-12:** question-spec consumers.

**Wave 9: tool boundary and guards (5).**
- **WPs, in merge order:** INFRA-5, TIME-5, SIM-3, TIME-4, EVAL-8.
- **INFRA-5:** the report tool-call boundary, including the tool_unknown rows.
- **TIME-5:** shadow numeric-coherence guard.
- **SIM-3:** simulation artifact hygiene.
- **TIME-4:** v3 quant sanity parity.
- **EVAL-8:** golden headline tiering.

**Wave 10: telemetry (5).**
- **WPs, in merge order:** RESEARCH-9, REPORT-11, SIM-8, INFRA-11, TIME-10.
- **RESEARCH-9:** citation-surgery telemetry.
- **REPORT-11:** probability-shape telemetry and objective_signals.
- **SIM-8:** the decision elicitor sees the period's events.
- **INFRA-11:** actor identity for non-Latin names.
- **TIME-10:** data vendor core.

**Wave 11: repair and escalation (5).**
- **WPs, in merge order:** INFRA-3, REPORT-3, RESEARCH-6, TIME-12, TIME-11.
- **INFRA-3:** length escalation.
- **REPORT-3:** alias-aware slot audit and repair.
- **RESEARCH-6:** forecaster attribution, shadow.
- **TIME-11 and TIME-12:** EDGAR and gateway plumbing.

**Wave 12: guards and shadow checks (5).**
- **WPs, in merge order:** INFRA-4, REPORT-9, EVAL-16, EVAL-19, EVAL-5.
- **INFRA-4:** non-finite guards.
- **REPORT-9:** shadow verified-figure check.
- **EVAL-16:** tool counters.
- **EVAL-19:** evaluation bundle.
- **EVAL-5:** market skill scorer.

**Wave 13: default-off policies (4).**
- **WPs, in merge order:** EVAL-14, REPORT-12, RESEARCH-10, SIM-7.
- **EVAL-14:** structured targets.
- **REPORT-12:** market-blend arithmetic.
- **RESEARCH-10:** evidence headers.
- **SIM-7:** overlay outcome power.

**Wave 14: opt-in passes (4).**
- **WPs, in merge order:** REPORT-13, SIM-4, TIME-13, EVAL-12.
- **REPORT-13:** counter-case pass.
- **SIM-4:** prior-echo diagnostic.
- **TIME-13:** data tools in the engine.
- **EVAL-12:** contamination probes.

**Wave 15: tail (2).**
- **WPs, in merge order:** RESEARCH-8, EVAL-20.
- **RESEARCH-8:** DERIVED findings.
- **EVAL-20:** block-movement study. It makes paid, opt-in calls, so running it needs owner authorization.

### Deferred and why

| WP | Candidates | Reason (verifier-grounded) | Salvage carried elsewhere |
|---|---|---|---|
| EVAL-21 | C21 | Value 2. Resolved-mode replays are always lookahead-inconclusive, because v3 as_of is today. Closed-book masked gaps flag easy questions as memorized. Actor-only masks re-identify trivially. I-21 already fences the golden set. | Outcome-free criteria and forecaster_view go to EVAL-9. The brief relabel goes to SIM-5. |
| EVAL-22 | P04 | Value 2, refuted. Per-report slope self-promotion conflicts with WP14/I-21 and run pinning. The gate stays inert for years (29 rows, 0 resolved). The backend write freeze violates I-20. | Strict stamps go to EVAL-2/3. The tz-aware created_at goes to EVAL-1. The shadow-only knob goes to EVAL-3. |
| EVAL-23 | P16 | Value 1, refuted. There is no resolved data until about 2028, and component critique has nothing to compare. It duplicates anchoring and recalibration, and putting a critic inside the monitor breaks its no-LLM contract. | Future work for WP14. |
| EVAL-24 | P18 | Value 2. The post-as_of tier has no valid corpus, power at n=8-30 is negligible, and the judge was never baselined. | Judge pinning, no cache, no failover and the tier-reroute fix go to EVAL-10. |
| TIME-14 | C24, P12 | Value 2, refuted. 0 of 344 binaries qualify. Drift dominates at 2-14 year horizons. 0 of 15 dossiers have series with 7 or more points. An undocumented Yahoo endpoint conflicts with ADR 0002 decision 2. | The drivers/indicators kernel goes to RESEARCH-11. The spine quantitative_facts gap stays with WP6. |
| RESEARCH-14 | C28, P29 | Value 2. DRF is already ahead: the CJK-aware self-stop, the overflow taxonomy, and research windows of 200k tokens or more make overflow unreachable. P29's parsers target providers DRF does not configure. | The evidence-preserving forced final goes to INFRA-5. Invalid-call counting goes to EVAL-16. |
| RESEARCH-15 | C45, P30 | Value 2. v3 binds exactly two static tools and ENGINE_VERSION owns tool changes. The defects sit in the dormant drf2 scaffold. | The native tool guard goes to INFRA-5. The negated-comparator parser fix goes to EVAL-14. |
| RESEARCH-16 | P24 | Value 2, refuted. The wasted-fetch rate is about 1%, below FinanceHarness's 2.1%. Pre-filling the cache with direct-HTTP text would degrade Firecrawl evidence. | The budget-denial miscount is fixed in RESEARCH-2. |
| RESEARCH-17 | P28 | Value 1, refuted. The LLM impact rating is unablated, top_k=20 never binds, and the adoption gate is powerless. | Relevance-ordered digest drops go to RESEARCH-10. |
| RESEARCH-18 | P31 | Value 2, refuted as a standalone. | The slot priority and never-ask rule go to RESEARCH-11. as_of pinning goes to TIME-1/TIME-7. |
| REPORT-14 | N02 | Value 2. 0 of 344 binary statements carry likelihood words. The evidence-state proposal conflates contested with thin evidence and would relax a publication gate. | The numeric core goes to REPORT-2 and REPORT-3. |
| REPORT-15 | P10 | Value 2, refuted. The default configuration gives the gate nothing to measure (K=1, sim weight 0, 0 market_influence stamps). The perturb arm is inert by construction, and it conflicts with I-21. | The cache-busting spine retry goes to REPORT-1. |
| REPORT-16 | P11 | Value 2. Fusion is a near no-op (6 of 344 anchored), channel priors cannot be fitted, and a probability-moving pool needs WP14. | Future ForecastBundle v2 and WP13. |
| REPORT-17 | P19 | Value 2. Inert on year-precision signposts. The "spread" is a relabelled adjustment size, and golden promotion violates I-21. | The v3 indicators kernel goes to RESEARCH-11. |
| REPORT-18 | P27 | Value 2, refuted. The actor concentration it targets never occurs (at most 2 binaries per actor). Pruned graphs cannot mine arcs, and the graph is non-authoritative under ADR 0002. | Drivers/indicators go to RESEARCH-11. Golden construction ideas go to EVAL-9. |
| SIM-9 | C48 | Value 2, refuted. It is an order-dependent aggregator rather than a market: tail-crushing, parameter-dependent, with a built-in cap. The WorldState pool already gives P(outcome). | None now; an expectation-probe kernel after WP13/14. |
| SIM-10 | P21 | Value 2. Paper evidence is qualitative, one local run has decisions.jsonl, and no threshold can be calibrated. | The coverage-aware verdict goes to SIM-1, prior echo to SIM-4 and unreachable events to SIM-3. |
| INFRA-15 | C46 | Value 2, refuted. The data already exists (v3 work-dir files and the agent_log cursor reader), so the gain is presentation only. | An optional UX ticket. |
| INFRA-16 | C47 | Value 2. doctor.sh and the uv lockfile already exist. | Declaring undeclared dependencies and CI --locked go to INFRA-12. The rest is a hygiene ticket. |

### Already in DRF (reuse, do not rebuild)

- **Evaluation-ledger isolation:** `forecast_ledger.evaluation_ledger_dir()` with the `record_class: evaluation` redirect and production-row filtering (Foglamp WP1).
- **Canonical JSON:** `actor_context.canonical_json_sha256` (strict, NaN-rejecting). EVAL-1 moves it into `utils/canonical_json.py`.
- **Env flag parsing:** the bridge's `_TRUTHY` and `_FALSY` sets (`linear_research.py:643-644`).
- **Actor matching:** `utils/actors.normalize_name` and `match_actor` (4 characters or more, fail-closed on ambiguity).
- **Legacy-engine behaviours v3 dropped:**
  - `_clamp_asof_reference`, restored by TIME-1;
  - `reconcile_quantitative` and `flag_implausible_quant`, restored by TIME-4;
  - `_is_dead_fetch`, restored by RESEARCH-1;
  - the forecast-inputs extraction behind `RESEARCH_FORECAST_INPUTS`, restored by RESEARCH-11.
- **Response cleanup:** the research gateway's flatten, strip-think and finish-reason sets. INFRA-1 shares them with the backend client.
- **Publication gate:** `publication_status` and the authoritative read-only final audit in `_enforce_final_publish_audit`.
- **Market cross-check:** the PM-2 Market Cross-Check renderer and `market_comparison.json`.
- **Market divergence:** the >10pp divergence enforcement.
- **Resolution enforcement:** `v1_resolve` already enforces publication. EVAL-4 only stops unmatched outcomes being persisted.
- **Binary anti-hedging:** the scorecard gate, contrarian framing and the low-probability top-up.
- **v3 output shape:** v3 emits a canonical probability block.
- **Spine-first report:** probabilities are derived before prose, with self-critique flags (`critiqued`).
- **v3 research engine:** the CJK-aware 60k self-stop and the overflow taxonomy. Only two static tools are bound, and `ENGINE_VERSION` owns tool changes.
- **Simulation state:** the WorldState linear pool with typed round statuses. `SIMULATION_FORECAST_EFFECT=diagnostic_only` keeps the simulation from moving published numbers.
- **Metering:** the fallback client's own `chat()` meters the call. The earlier "fallback calls unmetered" claim was wrong.
- **Ops tooling:** `doctor.sh`, the batch_runs smoke paths, the uv lockfile and the offline CI tiers.
- **Live progress data:** v3 writes plan, state and sources_ledger to the work directory, and the report's `agent_log` has a cursor reader.

### Licensing

- **TradingAgents (Apache-2.0).** Adapted code needs attribution.
  - TIME-10 adapts `tradingagents/dataflows/vendors/fred.py`. It creates the root `NOTICE` file, which does not exist today, and adds a file header.
  - TIME-11 adapts `sec_edgar.py` and appends to `NOTICE`.
  - Every other TradingAgents-inspired WP reimplements ideas in fresh code and wording, so it needs no `NOTICE` entry, only a docstring credit where its spec asks for one: REPORT-1, REPORT-4, REPORT-8, TIME-2 and TIME-7's as-of comparison rule.
- **FinanceHarness and StockAgent (no licence).** Ideas only. Never copy code, prompt text or schemas verbatim. This applies to REPORT-12's market-blend instructions, RESEARCH-11's `_T_QSPEC` and the FinanceHarness-inspired pieces of RESEARCH-1, RESEARCH-8, SIM-2 and SIM-7. Reviewers confirm this on every merge.

### Owner decisions to confirm during rollout

1. **Scored-ledger default:** EVAL-1's default `FORECAST_LEDGER_COMMIT_MODE=published` (unpublished reports leave the scored ledger).
2. **EVAL-2 as a shadow:** EVAL-2 lands as a WP13 shadow (ADR 0002 decision 5).
3. **As-of pin default:** TIME-1's `RESEARCH_AS_OF_PIN` defaults to true.
4. **FRED key:** FRED needs a free API key, against the keyless preference (TIME-10/13). EDGAR is keyless apart from a User-Agent carrying an email address.
5. **Hard rule change:** REPORT-3's `numeric` mode would change a hard publication rule, which needs a policy-version bump.
6. **WP14 promotions:** REPORT-11 guard, REPORT-12 blend, REPORT-13 counter-case, RESEARCH-13 packer and EVAL-14 targets are promoted only through a WP14 outcome-blind decision.
7. **Paid runs:** paid or live runs for EVAL-11, EVAL-12 and EVAL-20 need authorization.
8. **XRUN-1(c):** whether to gate XRUN-1(c) to `legacy_prompt` (SIM-4 note).
9. **Fallback threshold:** calibrating SIM-2's `DECISION_CHANNEL_FALLBACK_MAX_SHARE=0.5` after live runs.
10. **Default flips:** one live A/B each before flipping the defaults of RESEARCH-2, RESEARCH-3, RESEARCH-4 typing, RESEARCH-7, RESEARCH-10 and RESEARCH-11.
11. **Config strictness:** INFRA-14's strict validation. Boolean `1/yes/on` values become startup errors, with `CONFIG_STRICT_VALIDATION=false` as the escape hatch.

## Implementation record

81 of 81 work packages are merged into `feat/finharness-transplants`. Each was built in its own worktree and reviewed adversarially (implement, review, fix, repeated until the reviewer approved). Each wave was then merged and gated on the full offline suite. The knob column gives each new `Config` knob with its default; every knob is documented in `.env.example`.

### Wave 1: Foundations: hermetic tests, LLM transport, security containment, sealed ledger commits, eval statistics, honest probability parsing, v3 fetch and quant honesty

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| INFRA-12 | Hermetic test harness: ambient env scrub, no-egress guard, global state resets, FakeLLMClient parity, CI lockfile | merged | `b970599` | — |
| INFRA-10 | Identifier containment and local API hardening (path joins, rmtree, Host allowlist, secret env persistence) | merged | `1bad44b` | `APP_ALLOWED_HOSTS`, `APP_HOST_CHECK=true` |
| INFRA-1 | LLM transport normalization: finish reasons, empty/filtered completions, think-stripping, race-free per-call metadata | merged | `80e32a9` | `LLM_TRANSPORT_STRICT=true` |
| EVAL-1 | Publication-sealed, idempotent, self-contained forecast-ledger commits (commit after the final audit) | merged | `f168700` | `FORECAST_LEDGER_COMMIT_MODE=published`, `FORECAST_LEDGER_QUESTION_MAX_CHARS=4000`, `FORECAST_LEDGER_RECORD_UNPUBLISHED=true` |
| EVAL-7 | golden_eval honesty layer: eval_stats module, rigor block, duplicate-id fixes, score-ledger directory/scale fixes, atomic writes | merged | `56efdf3` | — |
| REPORT-1 | Honest probability parsing: typed coercion + explicit needs_review state (no 0.0 / uniform / 0.98 laundering) | merged | `7a43e6d` | `FORECAST_PROB_STRICT_PARSE=true` |
| RESEARCH-4 | Deterministic quantitative-row typing (reported/projected, target-date repair) and page verification in v3 finalize | merged | `a091603` | `RESEARCH_QUANT_TYPING=false`, `RESEARCH_VERIFIED_FACTS=true` |
| RESEARCH-1 | Fetch-layer extraction-shell classifier, provenance wall and hard per-call fetch bound | merged | `586d347` | `RESEARCH_FETCH_CALL_TIMEOUT_S=150`, `RESEARCH_FETCH_SHELL_DETECTION=true` |

### Wave 2: As-of pin and env-forwarding registry, market endDate hygiene, LLM client isolation, decision-channel verdict, narrative sync, golden data contract

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| TIME-1 | Pin v3 actors.json as_of_date to the plan as-of (live-run honesty fix) | merged | `83e5174` | `RESEARCH_AS_OF_PIN=true` |
| EVAL-10 | Shared prerequisite: LLMClient per-instance isolation (cache bypass, pinned model/no failover, non-default-provider tier fix) + binary_quality clobber fix + eval-judge hygiene | merged | `da9fa09` | — |
| TIME-3 | Polymarket endDate hygiene: expired markets never anchor binaries or seed SIM priors | merged | `80b3038` | `PREDICTION_MARKETS_END_DATE_GATE=true`, `PREDICTION_MARKETS_END_DATE_GRACE_HOURS=0` |
| SIM-1 | Shared decision-channel validity verdict: in-band parity with coverage-aware accounting; report block, chart and fork diff honour non-valid verdicts | merged | `49b4f85` | `REPORT_WORLDSTATE_HIDE_INVALID=true` |
| EVAL-9 | Golden set v2 data contract: outcome-free visible criteria, structural leak lint, evidence/recompute schema, event clusters, audit CLI | merged | `dc4cbc3` | — |
| REPORT-2 | Deterministic narrative sync: refresh stale probability numbers in headline / confidence_rationale / summaries after every probability move (P08 stage 1a) | merged | `2c1c719` | `REPORT_NARRATIVE_SYNC=true` |
| RESEARCH-2 | Typed source outcomes: honest failure counting, credential/quota refusal latch, infra-vs-content fetch sentinels, research health stage | merged | `0c0d409` | `PIPELINE_HEALTH_RESEARCH_STAGE=false`, `RESEARCH_SOURCE_TAXONOMY=false` |

### Wave 3: Evaluation-run containment, market settlement writer, research evidence windows, roster-bound decision validation, JSON repair turn, stage scorecard

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| EVAL-13 | Evaluation-run honesty: admission pin, evaluation-ledger routing, monitor exclusion, pinned target binding | merged | `dc5f760` | `EVAL_TARGET_REPAIR_DRAW=true` |
| EVAL-2 | Market settlement events v2: sealed/publishable-at-issue gate, anchor eligibility, outcome_known_at, prospective proof, grace terminals, 50/50 ambiguity | merged | `661d698` | `RESOLUTION_MARKET_MIN_EQUIVALENCE=exact`, `RESOLUTION_PENDING_GRACE_DAYS=180`, `RESOLUTION_SETTLE_LEDGER=true`, `RESOLUTION_SETTLE_MAX_TARGETS=200` |
| INFRA-2 | Structured-output repair turn in chat_json, cache discard of failed attempts, single-pass spine critique | merged | `b21f607` | `LLM_JSON_REPAIR_TURN=true`, `REPORT_CRITIQUE_SINGLE_PASS=true` |
| REPORT-7 | Research-side figure verification: quant verification labels, source-verified evidence windows in sources.json, handoff verified_facts.json (C11 phase 1a) | merged | `ae9635e` | — (reuses RESEARCH-4's `RESEARCH_VERIFIED_FACTS=true`) |
| SIM-2 | Roster-bound decision validation with reason-coded accounting, per-agent abstention/roster ids and a fallback-share verdict | merged | `cd1b279` | `DECISION_CHANNEL_FALLBACK_MAX_SHARE=0.5`, `DECISION_CHANNEL_MAX_ACTIVE=60`, `DECISION_CHANNEL_VALIDATION=true` |
| EVAL-15 | Deterministic per-stage scorecard sidecar + offline score CLI + honesty-critical env pins | merged | `924e0ff` | `STAGE_SCORECARD_ENABLED=true` |

### Wave 4: Calibration fold, typed absence markers, question spec, verbatim evidence spans, run-shape pin, scheduled-event provenance, world-clock absence states

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| INFRA-7 | Run-shape pin, drift detection and resume lineage guards | merged | `c021e6d` | `RESUME_LINEAGE_GUARDS=true`, `RUN_SHAPE_DRIFT_POLICY=record`, `RUN_SHAPE_PIN=true` |
| EVAL-3 | C03 part 2/3: settlement fold + single point-in-time admissible() gate for calibration and recalibration | merged | `649c04e` | `FORECAST_LEDGER_SETTLEMENT_FOLD=false`, `REPORT_RECALIBRATE_FROM_LEDGER=false` |
| REPORT-4 | Typed absence markers for report-stage prompt slots: section critique, spine lead/base-rate provenance, binary source rule, market status + leak sentinel | merged | `43692bb` | `REPORT_ABSENCE_MARKERS=true` |
| RESEARCH-11 | Question spec producer: persisted operational definition, resolution source, horizon and disclosed default assumptions (v3 plan phase) | merged | `f511a10` | `RESEARCH_FORECAST_INPUTS=true`, `RESEARCH_QUESTION_SPEC=false`, `RESEARCH_V3_FORECAST_INPUTS=false` |
| RESEARCH-7 | Verbatim evidence-span contract for v3 findings (audit-first, position-aware numbers, sources.json supports) | merged | `bdd3e10` | `RESEARCH_EVIDENCE_QUOTES=off`, `RESEARCH_EVIDENCE_SUPPORTS=false` |
| SIM-5 | Scheduled-event provenance: injected events never pose as actor behaviour (feed label, reaction step, report tools, post-hoc roster), honest world-brief label, affect-delivery telemetry, camel context regression test | merged | `9d57ed2` | `SIM_EVENT_PROVENANCE=true`, `SIM_WORLD_BRIEF_HONEST_LABEL=true` |
| REPORT-6 | Simulation world clock: distinguish first / quiet / unavailable / not-produced periods instead of '(first period)' | merged | `9a312f3` | `SIM_ABSENCE_MARKERS=true` |

### Wave 5: Hindcast policy (re-scoped), information walls, source publication dates, truthful period context, context propagation, metering fidelity

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| INFRA-9 | ContextVar propagation in worker pools and fork safety-policy inheritance | merged | `5b0bfd0` | `FORK_INHERIT_SAFETY_POLICY=true` |
| EVAL-17 | Metering fidelity: seed-sim spend metered once, resume-safe per-stage totals, research cache-read split, declared flat-rate providers | merged | `79eb901` | `LLM_SUBSCRIPTION_PROVIDERS` |
| TIME-6 | Hindcast policy pin and report-stage containment (no live odds, evaluation-ledger routing, no current track record) | merged | `ebc7c55` | — |
| REPORT-10 | Information walls: pin existing walls with prompt-capture/static tests, de-duplicate the binary draw's market exposure, honest anchoring labels | merged | `6c09062` | `FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE=false`, `REPORT_MARKET_XCHECK_DISCLOSURE=true` |
| TIME-2 | Capture source publication dates in v3 (sources.json date, tool row headers, SOURCE INDEX, References) | merged | `fb2476e` | `RESEARCH_SOURCE_DATES=false`, `RESEARCH_SOURCE_DATE_TEXT_FALLBACK=true` |
| SIM-6 | Truthful per-period context delivery: honest WORLD CLOCK header (placeholder, labels, staleness), missed-event catch-up for sampled actors, dead-round event carry, sectioned digest caps, reaction-step period context | merged | `c863ac3` | `SIM_EVENT_CATCHUP_MAX_CHARS=1200`, `SIM_PERIOD_CONTEXT_V2=true` |

### Wave 6: Hindcast admission, shadow backbone check, hollow-sim gate, absence discipline, manual settlement, import fences

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| TIME-7 | Hindcast admission: validated as_of, fail-closed gating, and v3 as-of injection into research | merged | `8b911d4` | `HINDCAST_ENABLED=false` |
| EVAL-11 | Shadow spine cross-backbone sensitivity check (opt-in, pinned per run, no probability change) | merged | `4c151a0` | `BACKBONE_CHECK_ENABLED=false`, `BACKBONE_CHECK_MAX_ABS_DELTA=0.15`, `BACKBONE_CHECK_PROVIDERS` |
| REPORT-5 | Fail-closed hollow/errored-simulation gate on the report signal pack | merged | `852b9b0` | `REPORT_SIGNAL_PACK_HEALTH_GATE=true` |
| RESEARCH-3 | Absence-of-evidence discipline: coverage-aware no-result text, absence rules, market-coverage line, partial-transport label fix, incidence telemetry | merged | `014c3c8` | `RESEARCH_ABSENCE_DISCIPLINE=false` |
| EVAL-4 | C03 part 3/3: manual settlement path (forecast_tools resolve CLI, v1_resolve hardening, correction/retraction events) | merged | `ba69871` | — |
| INFRA-13 | Import fences: AST policy test restricting LLM/HTTP egress imports to approved modules | merged | `fedaef3` | — |

### Wave 7: Point-in-time evidence gates, forecast-prompt context packer, market price-time provenance, config audit, quant-typing module, provider overrides

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| INFRA-14 | Config audit: strict bool/numeric/enum/range validation, ghost knob promotion, run-option validation | merged | `2d26cbb` | `CONFIG_STRICT_VALIDATION=true`, `LLM_HTTP_TIMEOUT_S=600`, `REPORT_TRANSLATION_CONTAMINATION_RETRIES=3`, `RESEARCH_EVIDENCE_GRADING=true` |
| INFRA-6 | Single provider request-override helper (UA, reasoning extra_body, temperature) shared by client, sim model factory and probes | merged | `9713b16` | — |
| TIME-8 | Point-in-time evidence gates for hindcast research: one availability rule, search/fetch gating, provider date bound, cache isolation | merged | `703b5b0` | `PIT_GATES=true`, `PIT_PROVIDER_DATE_BOUNDS=true`, `PIT_SAME_DAY_POLICY=exclude`, `PIT_SEARCH_OVERFETCH=1`, `PIT_UNDATED_POLICY=drop` |
| EVAL-6 | Market price-time provenance on anchors (quoted_at / snapshot_as_of / price_time + basis) | merged | `bc9f8a7` | `MARKET_ANCHOR_PRICE_TIME=true` |
| RESEARCH-5 | Typed key-metrics tables, persona expectation qualifier, unified projection classifier and observe-only projection-attribution lint | merged | `c50a492` | `QUANT_TYPED_RENDERING=false`, `REPORT_PROJECTION_LINT=true` |
| RESEARCH-13 | Forecast-prompt context packer: section-aware binary dossier, spine evidence pack, as_of-labelled timeline lanes | merged | `d764ddf` | `FORECAST_CONTEXT_PACK_BINARY=false`, `FORECAST_CONTEXT_PACK_BINARY_BUDGET=48000`, `FORECAST_CONTEXT_PACK_SPINE=false`, `FORECAST_CONTEXT_PACK_SPINE_BUDGET=14000`, `FORECAST_SCHEDULED_LIVE_WINDOW_DAYS=30`, `REPORT_CHRONOLOGY_ASOF_SPLIT=false` |

### Wave 8: PIT citation wall and integrity verdict, labelled verified-figures block, question-spec consumers, cost card, model provenance

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| INFRA-8 | Model provenance: requested vs served model per stage, research model identity, forecast.json provenance block | merged | `88bec63` | `RECORD_MODEL_PROVENANCE=true` |
| EVAL-18 | P20 part 2/2: slim per-pipeline cost card + config fingerprint + ledger config_hash + compute-matched helper | merged | `56e9a21` | `COST_CARD_ENABLED=true` |
| TIME-9 | Point-in-time citation wall, research audit artifact and hindcast integrity verdict | merged | `128f398` | — (reuses TIME-8's `PIT_GATES=true`) |
| REPORT-8 | Report-side labelled verified-figures block (replaces key-metrics table), Part-2 injection, market price as_of/quoted_at (C11 phase 1b) | merged | `44e53c9` | `REPORT_VERIFIED_FACTS_BLOCK=true`, `REPORT_VERIFIED_FACTS_MAX_CHARS=6000`, `REPORT_VERIFIED_FACTS_MAX_ROWS=40` |
| RESEARCH-12 | Question spec downstream consumers: sim horizon rung, spine block, resolution-section disclosure, forecast.json summary | merged | `b2fe6c2` | `QUESTION_SPEC_DOWNSTREAM=true` |

### Wave 9: Report tool-call boundary, shadow numeric-coherence guard, simulation artifact hygiene, v3 quant sanity parity, golden headline tiering

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| INFRA-5 | Report tool-call boundary: tolerant arg parsing, validation, uncharged rejections, evidence-preserving forced final, telemetry fix | merged | `fcf4d44` | `REPORT_NATIVE_FINAL_EVIDENCE_CHARS=12000`, `REPORT_NATIVE_FINAL_WITH_EVIDENCE=true`, `REPORT_TOOL_ARG_REPAIR=true`, `REPORT_TOOL_MAX_REJECTED_PER_SECTION=6` |
| TIME-5 | Shadow numeric-coherence guard for published binary thresholds (latest-actual status-quo and scale checks) | merged | `e57b26d` | `NUMERIC_GUARD_MODE=shadow`, `NUMERIC_GUARD_SCALE_RATIO=300`, `NUMERIC_GUARD_STATUS_QUO_MARGIN=0.25` |
| SIM-3 | Run-artifact hygiene: schedule-reachability audit, world_digest rotation, engagement-sample organic leak, world-state taxonomy marker re-sync | merged | `0e4a1eb` | `SIM_ORGANIC_EXCLUDES_ENGAGEMENT_SAMPLES=true`, `SIM_SCHEDULE_AUDIT=true` |
| TIME-4 | Restore v3 quantitative sanity parity (unit-scale reconciliation and future-dated actual flags) | merged | `3119671` | `RESEARCH_QUANT_RECONCILE=true` |
| EVAL-8 | Golden headline tiering: prospective vs hindcast rows, withheld headline, fail-closed exit | merged | `f523eb1` | `GOLDEN_HEADLINE_GATE=true`, `GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS=7` |

### Wave 10: Probability-shape telemetry, citation-surgery telemetry, decision elicitor events, actor identity, official-data vendor core

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| REPORT-11 | Probability-shape telemetry (pre/post-critique), ledger objective_signals, symmetric binary guard (flag-off) and DRF-2 skill de-Goodharting | merged | `a7beda0` | `FORECAST_BINARY_SYMMETRIC_GUARD=false`, `FORECAST_PROBABILITY_SHAPE=true` |
| RESEARCH-9 | Citation-surgery telemetry: report finalizer pre-audit repairs and v3 QA citation stats | merged | `f785fd3` | `REPORT_FINALIZATION_TELEMETRY=true`, `RESEARCH_V3_CITATION_STATS=true` |
| SIM-8 | Decision elicitor sees the period's scheduled events as labelled exogenous items (P23 follow-on) | merged | `d7b3b85` | `SIM_DECISION_EVENTS=true` (also reuses SIM-6's `SIM_PERIOD_CONTEXT_V2=true`) |
| INFRA-11 | Stable actor identity for non-Latin names and strict actor name matching | merged | `d130558` | `ACTOR_NAME_MATCH_STRICT=true` |
| TIME-10 | Official-data vendor core and FRED/ALFRED vintage-pinned macro series (pure module, mocked tests) | merged | `91bece6` | `DATA_FRED_CACHE_TTL_H=6`, `DATA_FRED_WINDOW_YEARS=10`, `DATA_TOOLS_CACHE_DIR`, `DATA_TOOL_TIMEOUT_S=20` |

### Wave 11: Alias-aware slot repair, max_tokens escalation, forecaster attribution (shadow), EDGAR statements and gateway plumbing

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| REPORT-3 | Alias-aware probability-slot audit (observe) + deterministic slot repair of outline summary and final prose (P08 stage 1b) | merged | `07e0d79` | `REPORT_LOGIC_NUMBER_GATE=observe`, `REPORT_LOGIC_NUMBER_REPAIR=false` |
| RESEARCH-6 | Forecaster attribution in fact extraction and cross-source forecast-dispersion diagnostics (shadow only) | merged | `b3e2715` | `REPORT_CONSENSUS_DIAGNOSTICS=off`, `RESEARCH_FORECASTER_ATTRIBUTION=false` |
| INFRA-3 | max_tokens escalation on empty length-truncated replies and fail-closed handling of truncated JSON artifacts | merged | `4755709` | `LLM_JSON_TRUNCATION_FAIL_CLOSED=true`, `LLM_LENGTH_ESCALATION=true`, `LLM_MAX_ESCALATIONS=2`, `LLM_MAX_TOKENS_CEILING=32768` |
| TIME-11 | SEC EDGAR as-filed company statements (companyfacts, filed on or before as_of) | merged | `40bc6d2` | `DATA_EDGAR_CACHE_TTL_H=24` |
| TIME-12 | Research gateway plumbing for official-data tools (schemas, budgets, ledger rows, counters) | merged | `2fcf7a9` | — |

### Wave 12: Non-finite guards and status-first error classification, shadow verified-figure check, tool counters and scorecard aggregate, eval bundle, market skill scorer

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| INFRA-4 | Non-finite number guards for LLM JSON and forecast artifacts; status-first LLM error classification | merged | `307099b` | `ARTIFACT_STRICT_JSON=true`, `LLM_ERROR_CLASSIFY_STATUS_FIRST=true`, `LLM_JSON_STRICT_NUMBERS=true`, `RESEARCH_JSON_STRICT_NUMBERS=true` |
| REPORT-9 | Shadow verified-figure check and figure_provenance.json sidecar (C11 phase 2, detection only) | merged | `a64d798` | `REPORT_VERIFIED_FIGURES_CHECK=true`, `REPORT_VERIFIED_FIGURE_REL_TOL=0.02` |
| EVAL-16 | P22 part 2/2: unknown/invalid tool-call counters + cross-run scorecard aggregate | merged | `f0ef86a` | — |
| EVAL-19 | P07 part 1/2: frozen evaluation bundle (in-pipeline capture + offline backfill + integrity verify) | merged | `196b3eb` | `EVAL_BUNDLE_CAPTURE=false`, `EVAL_DOSSIER_CHARS=16000` |
| EVAL-5 | Market-relative skill scorer: Brier skill vs the price the forecast saw and divergence hit rate vs a market-implied null | merged | `dc89859` | `FORECAST_SKILL_MIN_N=10`, `FORECAST_SKILL_SCORING=true` |

### Wave 13: Structured binary targets, market-blend arithmetic (default off), evidence headers and fair truncation, overlay outcome power

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| EVAL-14 | Structured numeric targets on binaries + same-target threshold-ladder audit + trimmed quantity-scoring core | merged | `9b65135` | `FORECAST_BINARY_STRUCTURED_TARGET=false` |
| REPORT-12 | Deterministic market-blend arithmetic for the 10pp divergence restatement + show-your-work line | merged | `30ab072` | `FORECAST_MARKET_BLEND_ARITHMETIC=false`, `FORECAST_MARKET_BLEND_WEIGHT_MAX=0.8` |
| RESEARCH-10 | Per-KIQ evidence count headers, sufficiency labels and fair deterministic digest truncation | merged | `6ebb867` | `RESEARCH_EVIDENCE_HEADERS=false`, `RESEARCH_TRUNCATION_FAIRNESS=false` |
| SIM-7 | Human-authored outcome_power overrides in scenario overlays (the counterfactual lever the overlay lacks) | merged | `8f9c5b5` | — |

### Wave 14: Counter-case pass (default off), prior-echo diagnostic, data-tool engine integration, contamination probes

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| REPORT-13 | Evidence-cited counter-case pass: one validated strong-tier call feeding Part-2 and dated update triggers (published probabilities untouched) | merged | `44a4561` | `REPORT_COUNTER_CASE=false`, `REPORT_COUNTER_CASE_EVIDENCE_CHARS=12000` |
| SIM-4 | Zero-LLM prior-echo diagnostic for the decision channel, plus a pinned ensemble seed derivation | merged | `9c48935` | `SIM_PRIOR_ECHO_DIAGNOSTIC=true` |
| TIME-13 | v3 engine integration of official-data tools (binding, dispatch, prompt, finalize, telemetry) | merged | `13d0bbe` | `DATA_QUANT_ROWS_MAX=12`, `FRED_API_KEY`, `RESEARCH_DATA_TOOLS`, `RESEARCH_LINEAR_DATA_CALLS_PER_KIQ=4`, `RESEARCH_LINEAR_MAX_DATA_CALLS_TOTAL=60`, `SEC_EDGAR_USER_AGENT` |
| EVAL-12 | Golden contamination probes: closed-book and outcome-recall arms with leak, collapse and budget guards | merged | `b3c6fd3` | `GOLDEN_PROBE_CONFIDENT_P=0.85`, `GOLDEN_PROBE_ENABLED=false`, `GOLDEN_PROBE_MAX_CALLS=120` |

### Wave 15: DERIVED findings and the label-free block-movement study

| WP | Title | State | Merge | Knobs (default) |
|---|---|---|---|---|
| RESEARCH-8 | Declarative DERIVED findings: hardened Decimal evaluator, operand-on-page verification, derived supports | merged | `a7ba053` | `RESEARCH_DERIVED_FINDINGS=false` |
| EVAL-20 | Label-free block-movement study with A/A noise floor over frozen bundles (per serving model) | merged | `0d559d0` | `EVAL_ARM_REPLICATES=3`, `EVAL_BOOTSTRAP_RESAMPLES=2000`, `EVAL_INERT_MARGIN=0.02`, `EVAL_PROBE_FIDELITY_MAX=0.10`, `EVAL_STUDY_MAX_CALLS=600`, `EVAL_TARGETS_PER_BUNDLE=2`, `VALUE_ADD_EVAL_ENABLED=false` |

### Follow-up packages (open-issues triage)

Each merged package reported its open issues. The orchestrator turned the real defects among them into follow-up packages. These ran through the same pipeline and merge gate. The rest of the triage is under "Open issues after implementation" below.

| WP | Title | Source issue | State | Merge | Knobs (default) |
|---|---|---|---|---|---|
| FU-1 | Backfill keeps the binary_quality keys EVAL-10 added | EVAL-10#1 | merged | `96705be` | — |
| FU-2 | Strict point-in-time wall in the research digest (owner decision: option a) | TIME-9#1 | merged | `caab1f7` | — |
| FU-3 | Hollow-run gating for plan_outline, the ReACT tools and what-if baselines | REPORT-5#1 | merged | `7fdaa0c` | — |
| FU-4 | Spine evidence pack gets the verified-figures block, not the unlabelled table | REPORT-8#1 | merged | `32a445d` | — |
| FU-5 | Expired-but-open markets labelled in the report's market comparison | TIME-3#1 | merged | `004d01e` | — |
| FU-6 | Market search tool: a timed-out snapshot is never 'verified_empty' | RESEARCH-3#1 | merged | `83c886a` | — |
| FU-7 | No model-volunteered market anchor inside a hindcast pin | TIME-6#1 | merged | `1816486` | — |
| FU-8 | The fork safety pin governs interview graph feedback | INFRA-9#1 | merged | `d569178` | — |
| FU-9 | Contested-claims table keeps room for quantitative reconcile rows | TIME-4#1 | merged | `8d60b28` | — |
| FU-10 | Prepare pack keeps previously matched rows at the cap | RESEARCH-6#1 | merged | `01c9234` | — |
| FU-11 | Per-row market price observation time for anchors | EVAL-6#1 | merged | `86102ef` | — |
| FU-12 | LLM JSON parser never raises on oversized integers or deep nesting | EVAL-20#open-a | merged | `5e5ac5c` | — |

### Gate results

Full offline backend suite (python -m pytest -q -p no:cacheprovider from backend/) plus frontend unit tests, run by the orchestrator on the integration branch after each wave's merges. Until the main@c20ec60 merge, 3 failures were known environment-only (two tests read the gitignored deer-flow-2.0.0 vendor tree, one compares a path pinned to the main checkout); main's CI fixes turned the two vendor-tree tests into skips and made the pinned-path test pass (the skills path in drf2/config/config.yaml is now relative and the test resolves it against the repo root). Logs before wave 7 lived in the session scratchpad, which was wiped; the counts are those recorded in the handoff at the time. Gate labels from wave 11a on name the orchestrator's merge batches (the label lists what each batch merged), not the roadmap's waves 1 to 15.

| Gate | Passed | Skipped | xfailed | Failed | Frontend | Note |
|---|---|---|---|---|---|---|
| baseline `1e40844` | 4,276 | 17 | 11 | 3 | — | 3 known environment-only |
| wave 1 | 5,081 | 17 | 11 | 3 | — | 3 known environment-only |
| wave 2 | 5,486 | 17 | 11 | 3 | — | 3 known environment-only |
| wave 3 (before EVAL-2/EVAL-13) | 6,915 | 17 | 11 | 3 | — | 3 known environment-only |
| wave 3 (final) | 7,040 | 17 | 11 | 3 | — | 3 known environment-only |
| wave 4 | 7,524 | 17 | 11 | 3 | — | 3 known environment-only |
| wave 4 (after round-3 fixes) + EVAL-3 | 7,542 | 17 | 11 | 3 | — | 3 known environment-only |
| wave 5 | 7,865 | 17 | 11 | 3 | — | 3 known environment-only |
| wave 6 | 8,226 | 17 | 11 | 3 | 76/76 | 3 known environment-only |
| wave 7 + main@c20ec60 merge | 9,026 | 19 | 11 | 1 | 79/79 | import fence flagged main's new urllib.request use in the demo exporter; ALLOW row added (b6d7cd7), fence test then passed |
| wave 8 part 1 (TIME-9, EVAL-18) | 9,164 | 19 | 11 | 4 | 79/79 | 2 from an EVAL-18 regression (fixed in 799aa64) and 2 from tracked demo files deleted by an external process (restored); the three affected files then passed |
| wave 8 (all five merged) | 9,272 | 19 | 11 | 1 | 79/79 | EVAL-18's join test asserted run.json's report block equals the provider pair; INFRA-8 adds provenance there. Assertion narrowed (948a792); the fingerprint still carries only the pair. cost_accounting/model_provenance/question_spec tests then passed |
| wave 9 part 1 (INFRA-5, TIME-5) | 9,617 | 19 | 11 | 0 | 79/79 |  |
| wave 10 (all five) + config-hash fix | 9,929 | 19 | 11 | 0 | 79/79 |  |
| wave 9 part 2 (TIME-4, SIM-3) | 10,301 | 19 | 11 | 0 | 79/79 |  |
| wave 9 complete (+EVAL-8) | 10,313 | 19 | 11 | 0 | 79/79 |  |
| wave 11a part 1 (INFRA-3, RESEARCH-6) | 10,438 | 19 | 11 | 0 | 79/79 |  |
| wave 17a (triage fix 7ec3fe9, REPORT-12 merge 30ab072) | 10,702 | 53 | 11 | 0 | 79/79 | skips +34 = REPORT-12's intended within-10pp-band parametrize skips |
| wave 19a (SIM-7, TIME-11, RESEARCH-10, FU-4, FU-6) | 10,946 | 53 | 11 | 0 | 79/79 |  |
| wave 21a (FU-8, FU-1) | 10,968 | 53 | 11 | 0 | 79/79 |  |
| wave 22a (FU-1 r2, FU-2, REPORT-3, REPORT-9) | 11,234 | 53 | 11 | 1 | 79/79 | 1 failure: test_wave9_visualizer.py::test_kaleido_png_pair_standalone_builder (kaleido PNG render returned None) while the machine's load average was ~170 from concurrent agent test runs; the file passes in isolation (waves/kaleido_tq.log, EXIT 0); no merged package touches the visualizer. Environmental flake, not a regression. |
| wave 23a (EVAL-19, TIME-12, INFRA-4) | 11,452 | 53 | 11 | 0 | 79/79 |  |
| wave 24a (EVAL-16, EVAL-19 round-3 lows, FU-9, SIM-4, FU-7, FU-10, EVAL-14, EVAL-20; head 0d559d0) | 11,722 | 53 | 11 | 0 | 79/79 |  |
| wave 25a (FU-5, FU-12, EVAL-12, FU-11; head 86102ef) | 11,952 | 53 | 11 | 0 | 79/79 |  |
| wave 26a (TIME-13, REPORT-9 fixes, FU-3; head 7fdaa0c) | 12,114 | 53 | 11 | 0 | 79/79 |  |
| wave 27a (EVAL-5, REPORT-13; head 44a4561) | 12,210 | 53 | 11 | 1 | 79/79 | test_golden_tiering::test_gate_disabled_legacy_keys: EVAL-8's pre-EVAL-8 byte pin did not expect EVAL-5's spec-required additive calibration_report key n_unmatched_outcome; fixed in the test (e2f2f35), as for EVAL-12's additive block; the file passes. |
| wave 28a (final: all 93 packages + docs; head dbc4435) | 12,410 | 53 | 11 | 0 | 79/79 |  |

### Integration commits

The orchestrator made these commits directly on the integration branch. They are merge conflict follow-ups, one post-merge review follow-up (RESEARCH-2's round-3 fixes), regressions the full-suite gate caught, small fixes from the open-issues triage, and the documentation pass:

- `57d0e65` fix(integration): never score a needs_review forecast in the sealed ledger commit [wave 1]
- `c1b0604` fix(research): round-3 review follow-ups for typed source outcomes [RESEARCH-2]
- `b6d7cd7` test(fences): allow the demo exporter's local graph-API read [integration]
- `799aa64` fix(telemetry): cost-card window note is a no-op on an orchestrator built without __init__ [integration]
- `948a792` test(telemetry): the report-stage restamp keeps INFRA-8's provenance beside the provider pair [integration]
- `ceb5327` fix(telemetry): fingerprint REPORT-11's binary symmetric guard in the config_hash [integration]
- `7ec3fe9` fix: close five small defects left open by merged work packages
- `e2f2f35` test(eval): EVAL-8's legacy-bytes pin strips EVAL-5's additive calibration key
- `dbc4435` docs: finharness transplants in the architecture guide and the README trust section
- `d5923c1` docs: correct section 20 and README trust section against the merged code

### Licensing

No FinanceHarness or StockAgent code was copied; both ship without a licence, so only their ideas were reimplemented. TradingAgents is Apache-2.0. Code adapted from it is attributed in the file header and in `NOTICE`, with the licence text in `LICENSES/Apache-2.0.txt`:

- `deerflow_bridge/data_tools.py`: the curated FRED alias table and realtime pinning, adapted from `tradingagents/dataflows/vendors/fred.py` (TIME-10), and the as-filed SEC EDGAR XBRL reading with its statement tag lists, adapted from `vendors/sec_edgar.py` (TIME-11).
- `backend/tests/test_data_tools_edgar.py`: fixtures modelled on TradingAgents' `tests/test_sec_edgar.py` (TIME-11).

Files that only reimplement an idea say so in a source comment ("Idea credit: TradingAgents (Apache-2.0)", or 思路来源 in Chinese-commented code such as REPORT-11's symmetric guard above `_BINARY_SYMMETRIC_GUARD` in `forecast_extractor.py`) and copy no code.

### Open issues after implementation

Every merged package returned its open issues: residual risks, known limits, things it found outside its scope. The orchestrator checked each one against the integrated branch. They fall into five groups.

1. **Already resolved by a later package.** These were re-checked in the code and need no work:
   - SIM-1's world-state header drift: SIM-3 re-synced the marker, so `forecast_extractor` reads both header spellings.
   - EVAL-3's retracted `scenario_set`: EVAL-4's `standing_events` never lets a retraction label a row.
   - EVAL-13's monitor reading `forecast.json` directly: it now loads through `allow_stale_policy=True`.
   - TIME-3's report-level assertion of `market_window_ended_excluded`: added by EVAL-10.
   - REPORT-7's notes for REPORT-8: `verified_facts.py` reads REPORT-7's `future_dated` stamp.
   - REPORT-6's stale world-clock comments: updated during integration.
   - REPORT-11's guard missing from the config fingerprint: fixed in `ceb5327`.
   - INFRA-13's merge hazard: the branch already contains main, and the ALLOW row is present.
   - INFRA-14's live `.env` value: an integer, so no import-time error.
2. **Fixed directly on the integration branch** (`7ec3fe9`, one regression test each):
   - The research gateway's think-tag stripper (INFRA-1, U+0130).
   - `binary_resolution_date` on `horizon_year: inf` (EVAL-2).
   - A preflight range rule for `GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS` (EVAL-8).
   - `write_run_summary` on a list-shaped config (SIM-3).
   - `scheduled_rerun.forecast_diff` reading a null probability as 0% (REPORT-1).
3. **Handed to follow-up packages FU-1 to FU-11.** These ran through the same implement, review and fix pipeline. The follow-up table above ("Follow-up packages (open-issues triage)") gives their state. A twelfth, FU-12, came from a later review: the LLM JSON parsers crashed on an oversized integer or deep nesting (also present on `main`).
4. **Left open on purpose.** These are the items below. Each needs an owner decision, a live run (agents were not allowed to make one), or a separate package for a defect that predates this program or for a residual limit of one of this program's own packages.
5. **Accepted limits.** These are documented in the code and pinned by tests (listed at the end).

#### Owner decisions

- **Forks that share the base graph (INFRA-9).** Should `sim_graph_feedback` be forced off for a fork that shares its base's `graph_id`, or should forks get their own graph? Today a warning makes the case visible. The spec required forks to inherit the base's settings verbatim.
- **Ledger owner of a shared-simulation regeneration (EVAL-13).** `ledger_identity_for_simulation` still picks the newest-first owner. An API regeneration on a shared base's simulation therefore records the child's `pipeline_id`, while `eval_run_id` and `cell_id` come from the base. Changing this would change EVAL-1's production attribution.
- **As-of disagreements (TIME-1).** Format-only disagreement records could be skipped once the model's value parses to the plan's date. That would change the spec's exact-string contract. Nothing reads `meta.as_of_model_disagreement` yet; a degradation event or a report note could surface it.
- **Decision-channel fallback share (SIM-2).** `DECISION_CHANNEL_FALLBACK_MAX_SHARE=0.5` is uncalibrated. Log live rates before tightening it.
- **Hindcast pin precedence (RESEARCH-6).** The pin is only a fallback for the actor as-of date: a full-day `actors.as_of_date` wins. For v3 hindcasts the two dates are equal, because TIME-1 pins them.

#### Live checks required before a default flips or a mode is promoted

The global rules forbade live LLM and network calls, so these checks are still owed:

- **RESEARCH-1.** One live quick run, which its spec's risk note asks for.
- **RESEARCH-11.** Cached tokens above zero on the plan call, plus a measure of plan-phase wall time, before its default flips.
- **RESEARCH-4.** A live A/B of the facts-prompt date rule before `RESEARCH_QUANT_TYPING` defaults to true.
- **RESEARCH-7.** An owner-approved audit-mode run before enforce mode (located share at least 0.8, QA passing).
- **REPORT-10.** Before promoting `FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE`, compare the rates of `market_table_strip_skipped` and `market_pack_truncated`.
- **EVAL-2.** Record a fixture from a real Gamma `/markets` response for an unknown id, before relying on terminals for missing markets.

#### Defects that predate this program (each needs its own package)

- **LLM provider routing (INFRA-6, EVAL-11).**
  - OASIS takes its endpoint from `LLM_BASE_URL`/`LLM_MODEL_NAME`, not from the provider `_resolve_provider` returns. A mismatch now warns.
  - The `LLMCache` key and the 422/429 breakers are keyed by `self.provider`, so a 429 from the fast-tier provider trips the primary's breaker.
  - A non-primary provider's `key_env` can hold a key mirrored by an earlier settings switch. `_build_ensemble_client` would send that key to the provider's default base URL.
- **Simulation traces (SIM-5).** Comment rows in `actions.jsonl` never carry `post_id`, because OASIS writes no trace `post_id`. A `comment_id → post_id` lookup in `_enrich_action_context` behind its own knob would fix reply attribution and `coalition_map`.
- **Run storage and resume (INFRA-7, RESEARCH-1, RESEARCH-4, EVAL-1).**
  - Forks share the base's handoff directory. A research recompute in a fork, and a batch fork's `ontology.json`, write into the base. The new guard fails closed rather than adding graph overwrites.
  - A resumed run reuses `synthesize`/`qa` artifacts written from facts that only a shell page verified.
  - An extract-only salvage of a v3 run inherits a stale `quant_freshness`: it keeps the v3 value and never recomputes it. Since TIME-4 (`f380810`), `quant_implausible` and `quant_unit_warnings` are dropped from the inherited v3 meta, and the salvage records its own values.
  - `load_research_dossier_for_simulation` matches only the pipeline's own simulation, so a seed member's API regeneration gets no dossier.
  - The legacy ledger writers (`append_forecast`, `append_golden_result`) merge a new row with a torn tail.
- **Research tools (RESEARCH-2, TIME-4).**
  - With `RESEARCH_SOURCE_TAXONOMY` off (the default), the Jina circuit breaker still counts a 4xx body that mentions a timeout as a transport failure. RESEARCH-2 (`c1b0604`) fixed this only with the knob on, so flipping that default (which needs its live comparison run) closes it.
  - The legacy `flag_implausible_quant` misses non-canonical `as_of_date` spellings.
- **Repository hygiene (EVAL-7, INFRA-12, INFRA-13).**
  - `app/utils/atomic.py` creates files with mode 0600 (`mkstemp`), and `-o /dev/stdout` fails for an atomic writer.
  - `networkx` and `mcp` are runtime imports that `backend/pyproject.toml` does not declare. Dependency changes were out of scope.
  - `backend/scripts/test_pipeline_resume.py` errors whenever pytest collects it.
  - The INFRA-13 import fence does not cover:
    - transitive egress through allowlisted transports (`report_agent` → `PolymarketClient`);
    - re-export laundering;
    - `camel.agents`;
    - non-literal dynamic imports.

    The single-platform simulation runners also have no usage accumulator.


#### Residual limits of this program's own packages (each needs its own package)

- **Simulation (SIM-1, SIM-6/SIM-8, REPORT-6).**
  - SIM-1 writes the decision-channel `validity` (with `validity_reasons` and `forecast_effect`) into the trajectory file, but `/api/simulation/<id>/trajectory` passes through only `schema_version`, `converged` and `settled_round`. It should expose the verdict so that any client charting the shares can warn on a non-valid run. No current frontend view calls this endpoint; the old Step 3 chart (`Step3Simulation.vue`) was removed in `5ee4215`.
  - Events carried by the in-band evolver (SIM-6's `_carry_events`, SIM-8's `_decision_carry`) are lost on a lossy resume.
  - The runner reads `inband_evo.latest_delta_state()` (REPORT-6) separately from `world_delta_text`, so the two could come from different snapshots; capturing both together would remove the gap.
- **Research tools (TIME-3).** The legacy actor-extraction prompt has no rule for the market rows TIME-3 labels "awaiting settlement".

#### Found after implementation (review rounds of the last packages)

- **Fallback sections keep TIME-9's per-claim wall (FU-2 review round 2).** In a gated hindcast, `_Engine._report_records` walls the deterministic fallback sections with `pit_wall_record(..., per_claim=True)`, which treats a trailing co-citation as one claim: with S2 withheld, "… 250 GW by 2030 [S1][S2]" is published as "… [S1]". FU-2 fixed this for the writers' digest only (its spec's scope). Proposed package: wall `_report_records` with the digest rule, update TIME-9's fallback tests, drop `per_claim` / `_citation_clusters`, and add a fallback test with the trailing "[S1][S2]" finding.
- **REPORT-3's opt-in repair tail (review round 5, all low, `REPORT_LOGIC_NUMBER_REPAIR=true` only).** A number-first slot whose subject narrows the event ("北美有70%的概率出现电力受限"), a free-standing name part followed by a rate or share ("电力受限（40%）的比例"), and lexicon gaps (上一稿, "the Fed base case", 卖方, 据X预测) are still rewritten. The default is off and the observe audit found no false repair in 29 archived reports; extend the guards before anyone turns the repair on.
- **FU-1: `binary_quality.ensemble.low_agreement` can name a row the backfill dropped**, so the Part-1 ensemble footnote can list it. The spec keeps the ensemble block as stored; fixing it needs a spec decision (filter the block, or have `render_binary_forecasts_block` show only retained ids).
- **SIM-7 (pre-existing):** Flask's `get_json` accepts NaN/Infinity, so a what-if overlay with a NaN outcome power skips that entry. Nothing raises: `_scenario_ledger_identity` hashes the overlay with `canonical_json_sha256(allow_nan=False)`, the hash fails, and the except branch falls back to `overlay={}`. Every non-finite fork with the same label therefore gets the same `scenario_key`, whatever its other overrides are (a silent ledger-identity collision). Reject non-finite JSON at the fork endpoint (`fork_scenario`), or hash a sanitised copy of the overlay.

- **FU-5's backfill cannot read current-format market snapshots (FU-5 review round 2 fixer).** `scripts/backfill_report_visuals.py` passes the raw `prediction_markets.json` to `render_market_comparison_block`, but the research bridge writes `{as_of, source, queries, markets}`, so a backfill sees no snapshot rows (no unmatched list, no saved-stamp fallback); only legacy list-format snapshots work. A plain unwrap is not enough: the live loader (`ReportAgent._load_prediction_markets`) applies hindcast containment, and a blind unwrap could put post-cutoff markets into a replayed hindcast report. Proposed package: share the live loader, containment included, with the backfill.
- **`meta.json` `completed_at` is naive local time (FU-5 review round 2 fixer).** `generate_report` writes `datetime.now().isoformat()`; the FU-5 backfill and `scripts/eval_bundle.py` read it as local time, so a replay on a machine in another timezone shifts the judging instant by the offset. Writing an aware UTC timestamp (and reading both forms) removes the ambiguity.
- **The Part-1 binary table and the PM-6 price-history charts show a window-ended market unlabelled (FU-5 review round 2, out of FU-5's scope).** `forecast_extractor.render_binary_forecasts_block` prints an ended market's price (e.g. '4% (Δ+26pt)') under "benchmarked against live prediction markets". Proposed: append `prediction_markets.window_ended_label` to the Part-1 anchor cell with the same injectable clock FU-5 added (live `market_clock_now()`, backfill the report's `completed_at`).
- **EVAL-14 residual parser limits (round-3 lows fixer).** "ever since" still counts as path wording ("stayed above X ever since" means always-above); the NO-verdict word list is open-ended; a sentence with an unrelated negation skips the direction check; the short-code ladder fallback links identical short labels (same unit, statistic and dates only; the audit is warn-only).
- **EVAL-20: `--allow-characterization` is a run-time flag, not registered in `study.json`,** so resuming a characterization-only study needs the flag again (by design: it does not change the study sha).
- **REPORT-9 residuals (round-2 fixer).** A bare parenthetical probability "rises in 2025 (70%)." is still read as a level (the same shape carries real levels, "176 TWh in 2023 (4.4%)"); the backfill compares only the markets the previous `figure_provenance.json` recorded, at its recorded prices; the backfill rebuilds the verified-figures block whenever `REPORT_VERIFIED_FACTS_BLOCK` is on, even for a live run that never built it (the new record carries its own `block_sha256`).
- **FU-12 scope (orchestrator).** The Claude-CLI envelope parse in `llm_client` and `json.loads` sites over model text outside the two central parsers were not audited for the int-digit-limit / RecursionError class; the CLI envelope carries model text as a JSON string, so it is not exposed.

- **FU-3 cosmetic (round-3 low):** on a run where `coalition_map` is hidden, the `faction_brief` tool description still says it is preferred over `coalition_map` (no leak; a call returns the note).
- **The comparison chapter is recognised only by a Chinese title (FU-3 round-2 fixer, pre-existing).** `_is_comparison_section` recognises the chapter only by the Chinese titles 情景对比/反事实 (`generate_report` checks it before `_prepend_comparison_table` runs), and `_render_comparison_table` writes a Chinese-only table, so an English report rarely reaches FU-3's English reader line (or the table). Proposed: detect the chapter by its outline role and render the table in the report language.
- **TIME-13's pinned flag-off digests (round-1 lows fixer).** `test_flag_off_run_artifacts_do_not_depend_on_an_unbound_request` pins sha256 of the fake run's sources.json, quantitative.json, verified_facts.json and KIQ tasks captured from the pre-TIME-13 engine; a later package that legitimately changes those artifacts must recapture them (and say why in its commit).
- **TIME-13 live check owed.** FRED/ALFRED and SEC EDGAR behaviour through the v3 engine is verified offline only (fakes and recorded vendor lookups); one live run with `RESEARCH_DATA_TOOLS=all` and real credentials should precede any default flip.

- **REPORT-9 conflict precision is low on real reports (round-3 review, shadow phase by design).** Simulated on local reports with every research row marked verified: 78 conflicts on one Chinese report and 9 on the English quantum report, every inspected one pairing two different metrics that share sentence words (268 GW vs 490.7 GW, $1.2T vs $820B, 6,623 MW vs 945 TWh). Before any enforcement: anchor each figure on its own clause (split at ；;，, and conjunctions) and require equal unit words in the plain class when both sides name one; measure on the shadow sidecars of live runs first.

- **RESEARCH-8 × TIME-13 order (RESEARCH-8 round-4 review: fail-closed, owner decision).** `_drop_data_contradictions` (TIME-13) runs right after verification and before `_derive_quant_rows` (RESEARCH-8), so a model quant row that states a value calculated from an official-data page is dropped as contradicted before it could gain `derived_from`. The DERIVED fact itself is unaffected; only quantitative.json loses the row, exactly as with RESEARCH-8 off. Exempting such rows would weaken TIME-13's contradiction check, so it is left for the owner to decide.

- **RESEARCH-8 fail-closed readings (round-4 fixer; owner decisions if loosened).** A share complement or sum over percentage operands ('100-a' = 32) states only in points, so "the rest is about 32%" is result_mismatch; a ratio-form growth without '*100' ('a/b-1', '(a/b)**(1/n)-1') stated as a percentage is result_mismatch. An explicit '*100' on a unit-keeping formula ('(a-b)*100' over GW → '2,400%') is still read as a percentage through scales_to_percent (kept for the legitimate 'a*100; a=0.37' → 37%); candidate follow-up: apply the unit rule before the literal-100 rule.

- **REPORT-13 residuals (round 7, documented in the module).** Change verbs between a hope word and its quantity ("成功的机会降至一半") pass, because the gap holds only linking words (adding 降至/升至 would also reject "出口机会降至一半"); cross-sentence probabilities and detached hedges are out of scope by decision; "五一成都…" and a sentence after "U.S." are fail-closed blocks. The pass is off by default; measure its output on a live run before turning it on.

#### Accepted limits (documented in code and pinned by tests)

- **INFRA-5 tool-call parser.** An unclosed prose brace before the real call, or more than 8 undecodable openers before it, is reported as `args_not_json`.
- **TIME-5 binary reading heuristics.** None of these occurs in the 354 real binaries:
  - a simple-past "never … above" is not negated;
  - polarity stated after the condition, and Chinese NO forms, read as YES;
  - the metric span keeps a "Resolves …" prefix;
  - "FY2026" ends on 31 December.
- **Text and date parsing.**
  - RESEARCH-13: quarter lists of three or more read only the last two quarters.
  - EVAL-9: three golden-set lint gaps.
  - RESEARCH-11: year-granularity horizon heuristics.
  - REPORT-2: the recall cost of the context rule.
- **Metering under-counts (EVAL-17, EVAL-18).** Spend can be under-counted in three cases: an orphaned seed killed before any state save, a detached subprocess that rewrites its telemetry after a resume, and a disk-full attempt. It is never double-counted.
- **INFRA-8.** The narrow stale-stash residual in the RUN record.
- **Think-tag stripping (INFRA-1).** A plain reply containing a literal `</think>` loses everything before it. This is the gateway's documented orphan-closer trade-off.
- **INFRA-3.** Two always-on additive call-meta items, which no artifact reads.
- **EVAL-4.** `resolved.json` lags a CLI correction until the next `POST /api/v1/resolve`; there is a narrow lock-free race on the legacy path.
- **TIME-7.** `start()` reads the clock twice around UTC midnight. This is harmless.

#### Notes for the documentation pass

- **INFRA-2.**
  - Snapshot keys `structured_outputs` and `structured_outputs_by_stage`.
  - The OASIS CLI model's token estimate under-counts a repair turn. `LLMMeter` records both calls.
- **TIME-2.** `sources.json` `modified_source`; `as_of_after_source` widens the window only for metadata modified dates.
- **RESEARCH-12.**
  - The bridge/backend parity pin for the question spec is `test_question_spec_downstream.py::test_golden_fixture_sha_equals_the_bridge_normalizer`.
  - The real maximum spine block size is about 2.56k characters, not the spec's estimate of about 800.
- **INFRA-14.** `backend/scripts/batch_runs.py` surfaces a strict-config `ConfigurationError` as a CLI exception.


## Appendices

### Appendix A — Candidate ledger (all 83 candidates)

Verdicts are the three adversarial verifier lenses in order source · gap · value (C = confirmed, R = refuted; a correction counts as confirmed). Value is the median of the mapper's and verifiers' 1–5 scores; effort S ≤ ½ day, M ≤ 2 days, L ≤ 1 week, XL > 1 week. DRF status is the state before this program as judged by the gap verifier.

| ID | Origin | Candidate | Verdicts | Value | Effort | DRF status | Work package(s) | Outcome |
|---|---|---|---|---|---|---|---|---|
| C01 | repo | Honest probability parsing with a NEEDS_REVIEW sentinel and type-aware field coercion | CCC | 3 | M | partial | REPORT-1 | merged |
| C02 | repo | Pre-research brief scoping that writes an operational contract (resolution criteria, horizon, assumptions) | CCC | 4 | L | partial | RESEARCH-11 | merged |
| C03 | repo | Close the resolution -> reflection -> lesson loop with point-in-time gating | CCC | 4 | L | partial | EVAL-2 | merged |
| C04 | repo | Explicit absence markers for every optional prompt slot | CCC | 3 | M | partial | REPORT-4 | merged |
| C05 | repo | Typed data-source failure taxonomy with in-band anti-fabrication sentinels and outage probes | CCC | 3 | M | partial | RESEARCH-2 | merged |
| C06 | repo | Vintage-correct structured data tools for research (FRED/ALFRED macro, SEC EDGAR as-filed facts) | CCC | 3 | L | absent | TIME-10 | merged |
| C07 | repo | Deterministic compute tier: calc tool, pass-by-reference tool payloads, and a derived-number ledger | CCC | 3 | L | partial | RESEARCH-8 | merged |
| C08 | repo | Hindcast-safe as-of enforcement: server-injected hidden as_of, date clamping, withholding live-only data | CCC | 4 | L | absent | TIME-7 | merged |
| C09 | repo | Adversarial pro/con debate and calibration panel judged by a deep-tier synthesizer before the spine is frozen | CCC | 3 | L | partial | REPORT-13 | merged |
| C10 | repo | Validated structured outputs: state-aware validator with targeted repair turns plus prompt-body output contra… | CCC | 3 | M | partial | INFRA-2 | merged |
| C11 | repo | Verified-facts block as source of truth for exact numbers, with a figure-provenance appendix and lint check | CCC | 4 | L | partial | REPORT-7 | merged |
| C12 | repo | Coverage-aware absence claims: 'unobserved' is not 'none found' | CCC | 3 | L | partial | RESEARCH-3 | merged |
| C13 | repo | Strict typed config parsing that fails loudly, with recorded config provenance | CCC | 3 | M | partial | INFRA-14 | merged |
| C14 | repo | Information walls between independent estimation, anchors and verdicts, enforced by tests | CCC | 4 | L | partial | REPORT-10 | merged |
| C15 | repo | Bounded automatic max_tokens escalation and a pure, testable model-call recovery policy | CCC | 3 | M | partial | INFRA-3 | merged |
| C16 | repo | Stated-intent elicitation and say-do consistency scoring inside a typed per-period phase protocol | CCC | 3 | L | partial | SIM-3 | merged |
| C17 | repo | Research retrieval hardening: search pre-flight readability check and fetch-layer robustness | CCC | 3 | L | partial | RESEARCH-1 | merged |
| C18 | repo | Extract source publication dates and apply one half-open as-of window rule | CCC | 4 | L | partial | TIME-2 | merged |
| C19 | repo | Forecast-ledger integrity: commit only after the publish audit, idempotent, complete rows, one shared seam | CCC | 3 | M | partial | EVAL-1 | merged |
| C20 | repo | Symmetric anti-hedge rule in every probability-producing prompt | CCC | 3 | M | partial | REPORT-11 | merged |
| C21 | repo | Masked (pseudonymized) replay to detect memorized-outcome leakage in backtests | CCC | 2 | L | absent | EVAL-21 | deferred |
| C22 | repo | Hermetic, invariant-enforcing test suite (socket refusal, env blanking, leak scans, rendered-prompt capture) | CCC | 3 | M | partial | INFRA-12 | merged |
| C23 | repo | Declarative provider and per-model capability registry for llm_client (incl. version-gated reasoning knobs) | CCC | 3 | L | partial | INFRA-6 | merged |
| C24 | repo | Deterministic market-threshold base-rate tools (point-in-time prices, realized vol, lognormal P, empirical ta… | CCR | 2 | L | absent | TIME-14 | deferred |
| C25 | repo | Deterministic spine arithmetic: LLM supplies judgment inputs, code computes, shows its work and sensitivity | CCC | 3 | L | partial | REPORT-12 | merged |
| C26 | repo | Decision-channel elicitation integrity: fallback tagging, reasoned abstention, seeded roster shuffling | CCC | 3 | M | partial | SIM-2 | merged |
| C27 | repo | Epistemic discipline: shared prompt blocks plus typed reported/projected and date-semantics fields on facts | CCC | 4 | L | partial | RESEARCH-4 | merged |
| C28 | repo | In-loop context compaction for research and report agent loops | CCC | 2 | M | partial | RESEARCH-14 | deferred |
| C29 | repo | Fold a run-shape config signature into resume-by-artifact identity | CCC | 3 | L | partial | INFRA-7 | merged |
| C30 | repo | Counterfactual evaluation arms: non-LLM control actors and leave-one-channel-out attribution | CCC | 3 | L | partial | SIM-4 | merged |
| C31 | repo | Actor capability state (outcome_power producer) enforced by validators and mutable by structural shocks | CCC | 3 | L | partial | SIM-7 | merged |
| C32 | repo | Verbatim evidence-quote contract with deterministic substring verification (optional cheap reader tier) | CCC | 4 | L | partial | RESEARCH-7 | merged |
| C33 | repo | Grounding finalization: fetched-only citability, bibliography stripping, orphan telemetry, guarded attribute-… | CCC | 3 | M | partial | RESEARCH-9 | merged |
| C34 | repo | Agent tool boundary: Pydantic schemas, schema-driven arg repair, never-raise typed dispatch, uniform trajecto… | CCC | 3 | M | partial | INFRA-5 | merged |
| C35 | repo | Polymarket anchor hygiene: reject markets past endDate and withhold live odds in past-as-of runs | CCC | 3 | M | partial | TIME-3 | merged |
| C36 | repo | Calibrated source relevance screening with deterministic count headers and fail-open unscreened banners | CCC | 3 | M | partial | RESEARCH-10 | merged |
| C37 | repo | Canonical entity identity cards injected across stages | CCC | 3 | L | partial | INFRA-11 | merged |
| C38 | repo | Harden I/O boundaries: path-safe ids, secret-scrubbed transport errors, 0600 key files | CCC | 3 | M | partial | INFRA-10 | merged |
| C39 | repo | Run-scoped config via ContextVar for concurrent pipelines | CCC | 3 | M | partial | INFRA-9 | merged |
| C40 | repo | Resumable backtest sweep harness with isolated ledgers and rendered caveats | CCC | 3 | L | partial | EVAL-13 | merged |
| C41 | repo | Transport response normalization: reasoning kept out of content, opaque state round-trip, streaming reassembly | CCC | 3 | L | partial | INFRA-1 | merged |
| C42 | repo | Round-prompt completeness for sim agents: role contract, world delta, event provenance, stance continuity | CCC | 3 | M | partial | SIM-5 | merged |
| C43 | repo | Pinned versioned model ids recorded per call, plus per-stage preflight completion probes | CCC | 3 | L | partial | INFRA-8 | merged |
| C44 | repo | Fail-closed data guards: filters raise on parse failure, NaN/Inf rejected at ingestion, strict JSON artifacts | CCC | 3 | M | partial | INFRA-4 | merged |
| C45 | repo | Tool/skill catalog discipline for drf2 and growing tool surfaces | CCC | 2 | M | partial | RESEARCH-15 | deferred |
| C46 | repo | Live progress event channel with a closed event vocabulary and authoritative terminal artifacts | CCR | 2 | M | partial | INFRA-15 | deferred |
| C47 | repo | Packaging hygiene and a headless CLI entry point | CCC | 2 | M | partial | INFRA-16 | deferred |
| C48 | repo | Optional intra-sim belief market producing a sim-implied probability | CCR | 2 | M | absent | SIM-9 | deferred |
| N01 | repo | Anchor-relative skill scoring for resolved forecasts (skill vs the market/prior it saw, divergence hit rate,… | CCC | 3 | M | partial | EVAL-5 | merged |
| N02 | repo | Canonical verbal-probability lexicon with label↔number consistency lint (plus an explicit 'contested vs thin'… | CCC | 2 | M | partial | REPORT-14 | deferred |
| N03 | repo | Expert-consensus capture as structured evidence: central tendency, dispersion, forecaster count, recency and… | CCC | 3 | M | partial | RESEARCH-6 | merged |
| N04 | repo | AST-enforced architecture fences: sanctioned importers for provider SDKs and network libraries (plus prompt-c… | CCC | 3 | S | absent | INFRA-13 | merged |
| P01 | paper | Point-in-time evidence gates for golden and backtest runs (availability time, derived-artifact inheritance, v… | CCC | 3 | L | absent | TIME-8 | merged |
| P02 | paper | Model knowledge-cutoff registry with post-cutoff headline scoring | CCC | 3 | L | absent | EVAL-8 | merged |
| P03 | paper | Contamination probes for golden eval: nested closed-book probe, masked arm, recall and unsourced-event checks | CCC | 3 | L | absent | EVAL-12 | merged |
| P04 | paper | Leakage-safe, held-out-validated recalibration and frozen learned-state snapshots | CCR | 2 | M | partial | EVAL-22 | deferred |
| P05 | paper | Deterministic temporal-availability audit with fail-closed evaluation admission | CCC | 3 | L | absent | EVAL-6 | merged |
| P06 | paper | Golden-eval statistical rigor and result-integrity checks | CCC | 3 | M | partial | EVAL-7 | merged |
| P07 | paper | Per-model stage and channel value-add arms with an A/A noise floor and frozen retrieval | CCC | 3 | L | partial | EVAL-20 | merged |
| P08 | paper | Deterministic logic-to-number consistency lint in report_lint and the publish gate | CCC | 3 | L | partial | REPORT-2 | merged |
| P09 | paper | Deterministic share-based evidence packer with a never-truncated 'latest developments <= as_of' lane | CCC | 4 | M | partial | RESEARCH-13 | merged |
| P10 | paper | Drop/perturb-one-channel fragility gate on published probabilities | CCR | 2 | M | partial | REPORT-15 | deferred |
| P11 | paper | Per-channel probability cards and ledger-weighted log-odds fusion with cross-channel conflict flags | CCC | 2 | L | partial | REPORT-16 | deferred |
| P12 | paper | Numeric-quantity lane: value-annotated timeline, deterministic feature card, anchored quantile path | CCR | 2 | L | absent | TIME-14 | deferred |
| P13 | paper | Plausibility and reference-band guards for every numeric output (LLM, tool or sim-emergent) | CCC | 3 | L | partial | TIME-5 | merged |
| P14 | paper | Probabilistic scoring for numeric-quantity forecasts (quantiles, pinball, coverage, persistence baseline) | CCC | 3 | M | absent | EVAL-14 | merged |
| P15 | paper | Backbone-sensitivity check that flags model-dependent forecasts and zeroes flipped sim signals | CCC | 3 | L | partial | EVAL-11 | merged |
| P16 | paper | Error-grounded lessons ledger: cross-fold support, held-out acceptance, ancestry-gated retrieval | CCR | 1 | L | absent | EVAL-23 | deferred |
| P17 | paper | Golden set v2: recomputable resolutions, dead-band ambiguity, balanced curation and mined candidates | CCC | 3 | L | partial | EVAL-9 | merged |
| P18 | paper | Two-tier (pre-as_of retrieval / post-as_of anticipation) rubric and hardened judge protocol | CCC | 2 | L | partial | EVAL-24 | deferred |
| P19 | paper | Dual-resolution spine drafts over a sourced catalyst calendar | CCC | 2 | L | partial | REPORT-17 | deferred |
| P20 | paper | Cost-quality accounting: full-pipeline Brier skill per token and a dollar Pareto frontier | CCC | 3 | L | partial | EVAL-17 | merged |
| P21 | paper | Output-side simulation health diagnostics: herding index, event response, order and persona effects | CCC | 2 | M | partial | SIM-10 | deferred |
| P22 | paper | Stage-level coverage suite with rule-scored exact metrics and a faithfulness/grounding panel | CCC | 3 | L | partial | EVAL-15 | merged |
| P23 | paper | Simulation prompt hygiene: always-present period header, separate event channel, nudge lint | CCC | 3 | L | partial | SIM-6 | merged |
| P24 | paper | Search pre-flight with cache warming; research budget caps treated as cost backstops | CCR | 2 | M | partial | RESEARCH-16 | deferred |
| P25 | paper | Grounding finalization evidence and a reports-vs-projects lint | CCC | 3 | L | partial | RESEARCH-5 | merged |
| P26 | paper | Decision-channel feasibility validation that emits the reserved INFEASIBLE round status | CCC | 3 | M | partial | SIM-1 | merged |
| P27 | paper | Graph situation mining to seed contested and causal-chain binaries with a per-actor entity budget | CCR | 2 | L | partial | REPORT-18 | deferred |
| P28 | paper | Impact-rated source triage per KIQ with fail-open retention | CCR | 1 | M | absent | RESEARCH-17 | deferred |
| P29 | paper | Error-classified model-call recovery with cache-safe compaction points | CCR | 2 | M | partial | RESEARCH-14 | deferred |
| P30 | paper | Constant tool registry, deferred tool catalog and a numeric-forecast recipe skill | CCC | 2 | L | partial | RESEARCH-15 | deferred |
| P31 | paper | Pre-research scoping that records default assumptions against the run's as_of | CCR | 2 | M | partial | RESEARCH-18 | deferred |

### Appendix B — Work packages

| WP | Wave | Title | Candidates | Decision | Effort | Result |
|---|---|---|---|---|---|---|
| EVAL-1 | 1 | Publication-sealed, idempotent, self-contained forecast-ledger commits (commit after the final audi… | C19 | implement | L | merged (f168700); knobs: FORECAST_LEDGER_COMMIT_MODE, FORECAST_LEDGER_QUESTION_MAX_CHARS, FORECAST_LEDGER_RECORD_UNPUBLISHED |
| EVAL-7 | 1 | golden_eval honesty layer: eval_stats module, rigor block, duplicate-id fixes, score-ledger directo… | P06 | implement | M | merged (56efdf3) |
| INFRA-1 | 1 | LLM transport normalization: finish reasons, empty/filtered completions, think-stripping, race-free… | C41 | implement | M | merged (80e32a9); knobs: LLM_TRANSPORT_STRICT |
| INFRA-10 | 1 | Identifier containment and local API hardening (path joins, rmtree, Host allowlist, secret env pers… | C38 | implement | M | merged (1bad44b); knobs: APP_ALLOWED_HOSTS, APP_HOST_CHECK |
| INFRA-12 | 1 | Hermetic test harness: ambient env scrub, no-egress guard, global state resets, FakeLLMClient parit… | C22 | implement | M | merged (b970599) |
| REPORT-1 | 1 | Honest probability parsing: typed coercion + explicit needs_review state (no 0.0 / uniform / 0.98 l… | C01 | implement | M | merged (7a43e6d); knobs: FORECAST_PROB_STRICT_PARSE |
| RESEARCH-1 | 1 | Fetch-layer extraction-shell classifier, provenance wall and hard per-call fetch bound | C17 | implement | M | merged (586d347); knobs: RESEARCH_FETCH_CALL_TIMEOUT_S, RESEARCH_FETCH_SHELL_DETECTION |
| RESEARCH-4 | 1 | Deterministic quantitative-row typing (reported/projected, target-date repair) and page verificatio… | C27 | implement | M | merged (a091603); knobs: RESEARCH_QUANT_TYPING, RESEARCH_VERIFIED_FACTS |
| EVAL-10 | 2 | Shared prerequisite: LLMClient per-instance isolation (cache bypass, pinned model/no failover, non-… | — | implement | S | merged (da9fa09) |
| EVAL-9 | 2 | Golden set v2 data contract: outcome-free visible criteria, structural leak lint, evidence/recomput… | P17 | implement | M | merged (dc4cbc3) |
| REPORT-2 | 2 | Deterministic narrative sync: refresh stale probability numbers in headline / confidence_rationale… | P08 | implement | M | merged (2c1c719); knobs: REPORT_NARRATIVE_SYNC |
| RESEARCH-2 | 2 | Typed source outcomes: honest failure counting, credential/quota refusal latch, infra-vs-content fe… | C05 | implement | M | merged (0c0d409); knobs: PIPELINE_HEALTH_RESEARCH_STAGE, RESEARCH_SOURCE_TAXONOMY |
| SIM-1 | 2 | Shared decision-channel validity verdict: in-band parity with coverage-aware accounting; report blo… | P26 | implement | M | merged (49b4f85); knobs: REPORT_WORLDSTATE_HIDE_INVALID |
| TIME-1 | 2 | Pin v3 actors.json as_of_date to the plan as-of (live-run honesty fix) | — | implement | S | merged (83e5174); knobs: RESEARCH_AS_OF_PIN |
| TIME-3 | 2 | Polymarket endDate hygiene: expired markets never anchor binaries or seed SIM priors | C35 | implement | S | merged (80b3038); knobs: PREDICTION_MARKETS_END_DATE_GATE, PREDICTION_MARKETS_END_DATE_GRACE_HOURS |
| EVAL-13 | 3 | Evaluation-run honesty: admission pin, evaluation-ledger routing, monitor exclusion, pinned target… | C40 | implement | L | merged (dc5f760); knobs: EVAL_TARGET_REPAIR_DRAW |
| EVAL-15 | 3 | Deterministic per-stage scorecard sidecar + offline score CLI + honesty-critical env pins | P22 | implement | M | merged (924e0ff); knobs: STAGE_SCORECARD_ENABLED |
| EVAL-2 | 3 | Market settlement events v2: sealed/publishable-at-issue gate, anchor eligibility, outcome_known_at… | C03 | implement | L | merged (661d698); knobs: RESOLUTION_MARKET_MIN_EQUIVALENCE, RESOLUTION_PENDING_GRACE_DAYS, RESOLUTION_SETTLE_LEDGER, RESOLUTION_SETTLE_MAX_TARGETS |
| INFRA-2 | 3 | Structured-output repair turn in chat_json, cache discard of failed attempts, single-pass spine cri… | C10 | implement | M | merged (b21f607); knobs: LLM_JSON_REPAIR_TURN, REPORT_CRITIQUE_SINGLE_PASS |
| REPORT-7 | 3 | Research-side figure verification: quant verification labels, source-verified evidence windows in s… | C11 | implement | M | merged (ae9635e); reuses RESEARCH_VERIFIED_FACTS (from RESEARCH-4) |
| SIM-2 | 3 | Roster-bound decision validation with reason-coded accounting, per-agent abstention/roster ids and… | C26 | implement | M | merged (cd1b279); knobs: DECISION_CHANNEL_FALLBACK_MAX_SHARE, DECISION_CHANNEL_MAX_ACTIVE, DECISION_CHANNEL_VALIDATION |
| EVAL-3 | 4 | C03 part 2/3: settlement fold + single point-in-time admissible() gate for calibration and recalibr… | — | implement | M | merged (649c04e); knobs: FORECAST_LEDGER_SETTLEMENT_FOLD, REPORT_RECALIBRATE_FROM_LEDGER |
| INFRA-7 | 4 | Run-shape pin, drift detection and resume lineage guards | C29 | implement | M | merged (c021e6d); knobs: RESUME_LINEAGE_GUARDS, RUN_SHAPE_DRIFT_POLICY, RUN_SHAPE_PIN |
| REPORT-4 | 4 | Typed absence markers for report-stage prompt slots: section critique, spine lead/base-rate provena… | C04 | implement | M | merged (43692bb); knobs: REPORT_ABSENCE_MARKERS |
| REPORT-6 | 4 | Simulation world clock: distinguish first / quiet / unavailable / not-produced periods instead of '… | — | implement | S | merged (9a312f3); knobs: SIM_ABSENCE_MARKERS |
| RESEARCH-11 | 4 | Question spec producer: persisted operational definition, resolution source, horizon and disclosed… | C02 | implement | M | merged (f511a10); knobs: RESEARCH_FORECAST_INPUTS, RESEARCH_QUESTION_SPEC, RESEARCH_V3_FORECAST_INPUTS |
| RESEARCH-7 | 4 | Verbatim evidence-span contract for v3 findings (audit-first, position-aware numbers, sources.json… | C32 | implement | M | merged (bdd3e10); knobs: RESEARCH_EVIDENCE_QUOTES, RESEARCH_EVIDENCE_SUPPORTS |
| SIM-5 | 4 | Scheduled-event provenance: injected events never pose as actor behaviour (feed label, reaction ste… | C42 | implement | M | merged (9d57ed2); knobs: SIM_EVENT_PROVENANCE, SIM_WORLD_BRIEF_HONEST_LABEL |
| EVAL-17 | 5 | Metering fidelity: seed-sim spend metered once, resume-safe per-stage totals, research cache-read s… | P20 | implement | M | merged (79eb901); knobs: LLM_SUBSCRIPTION_PROVIDERS |
| INFRA-9 | 5 | ContextVar propagation in worker pools and fork safety-policy inheritance | C39 | implement | S | merged (5b0bfd0); knobs: FORK_INHERIT_SAFETY_POLICY |
| REPORT-10 | 5 | Information walls: pin existing walls with prompt-capture/static tests, de-duplicate the binary dra… | C14 | implement | M | merged (6c09062); knobs: FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE, REPORT_MARKET_XCHECK_DISCLOSURE |
| SIM-6 | 5 | Truthful per-period context delivery: honest WORLD CLOCK header (placeholder, labels, staleness), m… | P23 | implement | M | merged (c863ac3); knobs: SIM_EVENT_CATCHUP_MAX_CHARS, SIM_PERIOD_CONTEXT_V2 |
| TIME-2 | 5 | Capture source publication dates in v3 (sources.json date, tool row headers, SOURCE INDEX, Referenc… | C18 | implement | M | merged (fb2476e); knobs: RESEARCH_SOURCE_DATES, RESEARCH_SOURCE_DATE_TEXT_FALLBACK |
| TIME-6 | 5 | Hindcast policy pin and report-stage containment (no live odds, evaluation-ledger routing, no curre… | — | implement | M | merged (ebc7c55) |
| EVAL-11 | 6 | Shadow spine cross-backbone sensitivity check (opt-in, pinned per run, no probability change) | P15 | implement | M | merged (4c151a0); knobs: BACKBONE_CHECK_ENABLED, BACKBONE_CHECK_MAX_ABS_DELTA, BACKBONE_CHECK_PROVIDERS |
| EVAL-4 | 6 | C03 part 3/3: manual settlement path (forecast_tools resolve CLI, v1_resolve hardening, correction/… | — | implement | M | merged (ba69871) |
| INFRA-13 | 6 | Import fences: AST policy test restricting LLM/HTTP egress imports to approved modules | N04 | implement | S | merged (fedaef3) |
| REPORT-5 | 6 | Fail-closed hollow/errored-simulation gate on the report signal pack | — | implement | S | merged (852b9b0); knobs: REPORT_SIGNAL_PACK_HEALTH_GATE |
| RESEARCH-3 | 6 | Absence-of-evidence discipline: coverage-aware no-result text, absence rules, market-coverage line,… | C12 | implement | S | merged (014c3c8); knobs: RESEARCH_ABSENCE_DISCIPLINE |
| TIME-7 | 6 | Hindcast admission: validated as_of, fail-closed gating, and v3 as-of injection into research | C08 | implement | M | merged (8b911d4); knobs: HINDCAST_ENABLED |
| EVAL-6 | 7 | Market price-time provenance on anchors (quoted_at / snapshot_as_of / price_time + basis) | P05 | implement | S | merged (bc9f8a7); knobs: MARKET_ANCHOR_PRICE_TIME |
| INFRA-14 | 7 | Config audit: strict bool/numeric/enum/range validation, ghost knob promotion, run-option validation | C13 | implement | M | merged (2d26cbb); knobs: CONFIG_STRICT_VALIDATION, LLM_HTTP_TIMEOUT_S, REPORT_TRANSLATION_CONTAMINATION_RETRIES, RESEARCH_EVIDENCE_GRADING |
| INFRA-6 | 7 | Single provider request-override helper (UA, reasoning extra_body, temperature) shared by client, s… | C23 | implement | S | merged (9713b16) |
| RESEARCH-13 | 7 | Forecast-prompt context packer: section-aware binary dossier, spine evidence pack, as_of-labelled t… | P09 | implement | M | merged (d764ddf); knobs: FORECAST_CONTEXT_PACK_BINARY, FORECAST_CONTEXT_PACK_BINARY_BUDGET, FORECAST_CONTEXT_PACK_SPINE, FORECAST_CONTEXT_PACK_SPINE_BUDGET, FORECAST_SCHEDULED_LIVE_WINDOW_DAYS, REPORT_CHRONOLOGY_ASOF_SPLIT |
| RESEARCH-5 | 7 | Typed key-metrics tables, persona expectation qualifier, unified projection classifier and observe-… | P25 | implement | M | merged (c50a492); knobs: QUANT_TYPED_RENDERING, REPORT_PROJECTION_LINT |
| TIME-8 | 7 | Point-in-time evidence gates for hindcast research: one availability rule, search/fetch gating, pro… | P01 | implement | L | merged (703b5b0); knobs: PIT_GATES, PIT_PROVIDER_DATE_BOUNDS, PIT_SAME_DAY_POLICY, PIT_SEARCH_OVERFETCH, PIT_UNDATED_POLICY |
| EVAL-18 | 8 | P20 part 2/2: slim per-pipeline cost card + config fingerprint + ledger config_hash + compute-match… | — | implement | M | merged (56e9a21); knobs: COST_CARD_ENABLED |
| INFRA-8 | 8 | Model provenance: requested vs served model per stage, research model identity, forecast.json prove… | C43 | implement | M | merged (88bec63); knobs: RECORD_MODEL_PROVENANCE |
| REPORT-8 | 8 | Report-side labelled verified-figures block (replaces key-metrics table), Part-2 injection, market… | — | implement | M | merged (44e53c9); knobs: REPORT_VERIFIED_FACTS_BLOCK, REPORT_VERIFIED_FACTS_MAX_CHARS, REPORT_VERIFIED_FACTS_MAX_ROWS |
| RESEARCH-12 | 8 | Question spec downstream consumers: sim horizon rung, spine block, resolution-section disclosure, f… | — | implement | S | merged (b2fe6c2); knobs: QUESTION_SPEC_DOWNSTREAM |
| TIME-9 | 8 | Point-in-time citation wall, research audit artifact and hindcast integrity verdict | — | implement | M | merged (128f398); reuses PIT_GATES (from TIME-8) |
| EVAL-8 | 9 | Golden headline tiering: prospective vs hindcast rows, withheld headline, fail-closed exit | P02 | implement | S | merged (f523eb1); knobs: GOLDEN_HEADLINE_GATE, GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS |
| INFRA-5 | 9 | Report tool-call boundary: tolerant arg parsing, validation, uncharged rejections, evidence-preserv… | C34 | implement | M | merged (fcf4d44); knobs: REPORT_NATIVE_FINAL_EVIDENCE_CHARS, REPORT_NATIVE_FINAL_WITH_EVIDENCE, REPORT_TOOL_ARG_REPAIR, REPORT_TOOL_MAX_REJECTED_PER_SECTION |
| SIM-3 | 9 | Run-artifact hygiene: schedule-reachability audit, world_digest rotation, engagement-sample organic… | C16 | implement | S | merged (0e4a1eb); knobs: SIM_ORGANIC_EXCLUDES_ENGAGEMENT_SAMPLES, SIM_SCHEDULE_AUDIT |
| TIME-4 | 9 | Restore v3 quantitative sanity parity (unit-scale reconciliation and future-dated actual flags) | — | implement | S | merged (3119671); knobs: RESEARCH_QUANT_RECONCILE |
| TIME-5 | 9 | Shadow numeric-coherence guard for published binary thresholds (latest-actual status-quo and scale… | P13 | implement | M | merged (e57b26d); knobs: NUMERIC_GUARD_MODE, NUMERIC_GUARD_SCALE_RATIO, NUMERIC_GUARD_STATUS_QUO_MARGIN |
| INFRA-11 | 10 | Stable actor identity for non-Latin names and strict actor name matching | C37 | implement | S | merged (d130558); knobs: ACTOR_NAME_MATCH_STRICT |
| REPORT-11 | 10 | Probability-shape telemetry (pre/post-critique), ledger objective_signals, symmetric binary guard (… | C20 | implement | M | merged (a7beda0); knobs: FORECAST_BINARY_SYMMETRIC_GUARD, FORECAST_PROBABILITY_SHAPE |
| RESEARCH-9 | 10 | Citation-surgery telemetry: report finalizer pre-audit repairs and v3 QA citation stats | C33 | implement | M | merged (f785fd3); knobs: REPORT_FINALIZATION_TELEMETRY, RESEARCH_V3_CITATION_STATS |
| SIM-8 | 10 | Decision elicitor sees the period's scheduled events as labelled exogenous items (P23 follow-on) | — | implement | S | merged (d7b3b85); knobs: SIM_DECISION_EVENTS; reuses SIM_PERIOD_CONTEXT_V2 (from SIM-6) |
| TIME-10 | 10 | Official-data vendor core and FRED/ALFRED vintage-pinned macro series (pure module, mocked tests) | C06 | implement | M | merged (91bece6); knobs: DATA_FRED_CACHE_TTL_H, DATA_FRED_WINDOW_YEARS, DATA_TOOLS_CACHE_DIR, DATA_TOOL_TIMEOUT_S |
| INFRA-3 | 11 | max_tokens escalation on empty length-truncated replies and fail-closed handling of truncated JSON… | C15 | implement | M | merged (4755709); knobs: LLM_JSON_TRUNCATION_FAIL_CLOSED, LLM_LENGTH_ESCALATION, LLM_MAX_ESCALATIONS, LLM_MAX_TOKENS_CEILING |
| REPORT-3 | 11 | Alias-aware probability-slot audit (observe) + deterministic slot repair of outline summary and fin… | — | implement | M | merged (07e0d79); knobs: REPORT_LOGIC_NUMBER_GATE, REPORT_LOGIC_NUMBER_REPAIR |
| RESEARCH-6 | 11 | Forecaster attribution in fact extraction and cross-source forecast-dispersion diagnostics (shadow… | N03 | implement | M | merged (b3e2715); knobs: REPORT_CONSENSUS_DIAGNOSTICS, RESEARCH_FORECASTER_ATTRIBUTION |
| TIME-11 | 11 | SEC EDGAR as-filed company statements (companyfacts, filed on or before as_of) | — | implement | M | merged (40bc6d2); knobs: DATA_EDGAR_CACHE_TTL_H |
| TIME-12 | 11 | Research gateway plumbing for official-data tools (schemas, budgets, ledger rows, counters) | — | implement | M | merged (2fcf7a9) |
| EVAL-16 | 12 | P22 part 2/2: unknown/invalid tool-call counters + cross-run scorecard aggregate | — | implement | S | merged (f0ef86a) |
| EVAL-19 | 12 | P07 part 1/2: frozen evaluation bundle (in-pipeline capture + offline backfill + integrity verify) | — | implement | M | merged (196b3eb); knobs: EVAL_BUNDLE_CAPTURE, EVAL_DOSSIER_CHARS |
| EVAL-5 | 12 | Market-relative skill scorer: Brier skill vs the price the forecast saw and divergence hit rate vs… | N01 | implement | M | merged (dc89859); knobs: FORECAST_SKILL_MIN_N, FORECAST_SKILL_SCORING |
| INFRA-4 | 12 | Non-finite number guards for LLM JSON and forecast artifacts; status-first LLM error classification | C44 | implement | M | merged (307099b); knobs: ARTIFACT_STRICT_JSON, LLM_ERROR_CLASSIFY_STATUS_FIRST, LLM_JSON_STRICT_NUMBERS, RESEARCH_JSON_STRICT_NUMBERS |
| REPORT-9 | 12 | Shadow verified-figure check and figure_provenance.json sidecar (C11 phase 2, detection only) | — | implement | M | merged (a64d798); knobs: REPORT_VERIFIED_FIGURES_CHECK, REPORT_VERIFIED_FIGURE_REL_TOL |
| EVAL-14 | 13 | Structured numeric targets on binaries + same-target threshold-ladder audit + trimmed quantity-scor… | P14 | implement | M | merged (9b65135); knobs: FORECAST_BINARY_STRUCTURED_TARGET |
| REPORT-12 | 13 | Deterministic market-blend arithmetic for the 10pp divergence restatement + show-your-work line | C25 | implement | S | merged (30ab072); knobs: FORECAST_MARKET_BLEND_ARITHMETIC, FORECAST_MARKET_BLEND_WEIGHT_MAX |
| RESEARCH-10 | 13 | Per-KIQ evidence count headers, sufficiency labels and fair deterministic digest truncation | C36 | implement | S | merged (6ebb867); knobs: RESEARCH_EVIDENCE_HEADERS, RESEARCH_TRUNCATION_FAIRNESS |
| SIM-7 | 13 | Human-authored outcome_power overrides in scenario overlays (the counterfactual lever the overlay l… | C31 | implement | S | merged (8f9c5b5) |
| EVAL-12 | 14 | Golden contamination probes: closed-book and outcome-recall arms with leak, collapse and budget gua… | P03 | implement | M | merged (b3c6fd3); knobs: GOLDEN_PROBE_CONFIDENT_P, GOLDEN_PROBE_ENABLED, GOLDEN_PROBE_MAX_CALLS |
| REPORT-13 | 14 | Evidence-cited counter-case pass: one validated strong-tier call feeding Part-2 and dated update tr… | C09 | implement | M | merged (44a4561); knobs: REPORT_COUNTER_CASE, REPORT_COUNTER_CASE_EVIDENCE_CHARS |
| SIM-4 | 14 | Zero-LLM prior-echo diagnostic for the decision channel, plus a pinned ensemble seed derivation | C30 | implement | S | merged (9c48935); knobs: SIM_PRIOR_ECHO_DIAGNOSTIC |
| TIME-13 | 14 | v3 engine integration of official-data tools (binding, dispatch, prompt, finalize, telemetry) | — | implement | L | merged (13d0bbe); knobs: DATA_QUANT_ROWS_MAX, FRED_API_KEY, RESEARCH_DATA_TOOLS, RESEARCH_LINEAR_DATA_CALLS_PER_KIQ, RESEARCH_LINEAR_MAX_DATA_CALLS_TOTAL, SEC_EDGAR_USER_AGENT |
| EVAL-20 | 15 | Label-free block-movement study with A/A noise floor over frozen bundles (per serving model) | P07 | implement | L | merged (0d559d0); knobs: EVAL_ARM_REPLICATES, EVAL_BOOTSTRAP_RESAMPLES, EVAL_INERT_MARGIN, EVAL_PROBE_FIDELITY_MAX, EVAL_STUDY_MAX_CALLS, EVAL_TARGETS_PER_BUNDLE, VALUE_ADD_EVAL_ENABLED |
| RESEARCH-8 | 15 | Declarative DERIVED findings: hardened Decimal evaluator, operand-on-page verification, derived sup… | C07 | implement | M | merged (a7ba053); knobs: RESEARCH_DERIVED_FINDINGS |
| EVAL-21 | — | Defer C21 masked (pseudonymized) replay | C21 | defer | L | deferred: Consensus value 2 (below the implement bar). Value verifier: resolved-mode replays are always inconclusive_evidence_lookahead (v3 as_of = today, linear_research.py:4213), the closed-book named-vs-mas… |
| EVAL-22 | — | Defer P04 held-out recalibration promotion and frozen learned-state snapshots | P04 | defer | L | deferred: Consensus value 2 and refuted by the value lens: per-report self-promotion of a slope conflicts with WP14/I-21 and run pinning (ADR 0002 decisions 5-6), the gate is inert for years (29 rows, 0 resolv… |
| EVAL-23 | — | Defer P16 error-grounded lessons ledger | P16 | defer | XL | deferred: Consensus value 1, refuted by the value lens: no resolved data (gate needs ~80+ resolved binaries; earliest realistic ~2028), component-aware critique has almost nothing to compare (6/344 anchored, 0… |
| EVAL-24 | — | Defer P18 two-tier rubric and hardened judge protocol | P18 | defer | L | deferred: Consensus value 2. The post-as_of tier has no valid corpus (0 resolved ledger rows, undated sources, famous-outcome golden set), statistical power at n=8-30 is negligible, the existing judge harness… |
| INFRA-15 | — | Live research/report progress event stream (deferred) | C46 | defer | S | deferred: Consensus value 2 and the value-lens verifier refuted the core claim: the data the candidate proposes to emit already exists in DRF (v3 research writes state/plan/sources_ledger to the work dir; the… |
| INFRA-16 | — | Packaging and install hygiene (deferred to a separate hygiene ticket) | C47 | defer | S | deferred: Consensus value 2; DRF already has doctor.sh, batch_runs smoke paths and a uv lockfile. The parts with real value (CI uses --locked, dead CI steps removed) are absorbed by INFRA-12. The remainder is… |
| REPORT-14 | — | Defer: canonical verbal-probability lexicon, label-number lint and contested-vs-thin evidence state | N02 | defer | S | deferred: Consensus value 2 (< 3). Verifiers measured almost nothing to fix: 0 of 344 binary statements contain a likelihood word; the verbal band lint found 3 alias-attached terms and 1 false positive in 12 r… |
| REPORT-15 | — | Defer: drop/perturb-one-channel fragility gate on published probabilities | P10 | defer | M | deferred: Consensus value 2 and refuted by the value-lens verifier. In the default configuration the gate has ~nothing to measure (K=1, ensemble off, sim weight 0 under diagnostic_only; 0 market_influence stam… |
| REPORT-16 | — | Defer: per-channel probability cards and ledger-weighted log-odds fusion | P11 | defer | M | deferred: Consensus value 2 (< 3). The fusion engine is a near no-op on DRF data (6 of 344 binaries anchored, 1 exact with match_confidence >= 0.6); channel priors cannot be fitted (ledger 29 rows, 0 resolved;… |
| REPORT-17 | — | Defer: dual-resolution spine drafts over a sourced catalyst calendar | P19 | defer | M | deferred: Consensus value 2 (< 3). The dual-draft pooling would be inert on DRF's long-horizon, year-precision signposts (eligibility needs day/month precision) and on golden questions (the catalyst is the res… |
| REPORT-18 | — | Defer: graph situation mining to seed binaries with a per-actor entity budget | P27 | defer | L | deferred: Consensus value 2 and refuted by the value-lens verifier. The paper's mechanism builds a benchmark, not better forecasts; the actor concentration the budget targets never occurs (max 2 binaries per a… |
| RESEARCH-14 | — | In-loop context compaction and error-classified model-call recovery (defer) | C28, P29 | defer | S | deferred: C28 consensus value 2; P29 value 2 with a value-lens refutation. Both would be built on one mechanism: overflow and elision recovery. The research half is already DRF-ahead: - KiqAgent's CJK-aware 60… |
| RESEARCH-15 | — | Tool/skill catalog discipline and numeric-forecast recipe skill (defer) | C45, P30 | defer | S | deferred: C45 value 2; P30 value 2 (extends C45). On the live path the principle is already present and ahead of FinanceHarness: v3 binds exactly two static tools, and ENGINE_VERSION owns tool changes. The rea… |
| RESEARCH-16 | — | Search pre-flight with cache warming; budget caps as backstops (defer) | P24 | defer | S | deferred: P24 value 2, refuted on value; C17's verifiers also dropped the pre-flight. DRF's measured wasted-fetch rate is about 0.85-1% with Firecrawl, below FinanceHarness's with-prefetch 2.1%. The leaking pa… |
| RESEARCH-17 | — | Impact-rated per-KIQ source triage (defer) | P28 | defer | S | deferred: P28 value 1, refuted on value. The LLM impact rating is unablated in F2Agent. top_k=20 can never bind: at most 15 findings per KIQ. The adoption gate is statistically powerless. The verifiers' determ… |
| RESEARCH-18 | — | Standalone pre-research default-assumption scoping (defer; absorbed by RESEARCH-11) | P31 | defer | S | deferred: P31 value 2, refuted on value: 'drop P31 as a standalone candidate'. Its surviving pieces: - The assumption-slot priority (horizon > resolution_source > units > entity), cap 3 and never-ask are folde… |
| SIM-10 | — | Output-side population diagnostics: herding index, event response, order and persona effects (defer… | P21 | defer | M | deferred: P21 has consensus value 2, below the required 3. The source and value verifiers both lowered it to 2. Its paper evidence is qualitative only: one t-SNE per backbone, with SAP inconsistent on trend-fo… |
| SIM-9 | — | Intra-sim LMSR belief market producing a sim-implied probability (deferred) | C48 | defer | L | deferred: C48 fails the implementation bar on two counts. Its consensus value is 2, below the required 3. Its value-lens verifier REFUTED it: an LMSR whose prices are hidden, whose 'traders' all come from one… |
| TIME-14 | — | Defer market-threshold reference-class tools and the numeric-quantity lane | C24, P12 | defer | XL | deferred: Both fail the implement bar. C24: consensus value 2, value lens REFUTED — 0 of 344 binaries across 33 stored reports and 2 of 30 golden questions (both famous-outcome touch questions) qualify; at DRF… |
