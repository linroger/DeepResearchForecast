# bridge-tools-skills — Bridge market tools and DeerFlow skills

Slice owner files (branch `main`, on-disk checkout, read 2026-10-11):

| File | Lines | Git-tracked |
|---|---:|---|
| `deerflow_bridge/market_tools.py` | 648 | yes |
| `deerflow_bridge/skills/prediction-markets/SKILL.md` | 93 | yes |
| `deerflow_bridge/skills/deep-research/SKILL.md` | 95 | yes |
| `deerflow_bridge/skills/deep-research/references/final-dossier-contract.md` | 66 | yes |
| `deerflow_bridge/skills/deep-research/references/source-tradecraft.md` | 73 | yes |
| `deerflow_bridge/skills/actor-ontology-research/SKILL.md` | 215 | yes |
| `deerflow_bridge/skills/actor-ontology-research/references/actor-intelligence-contract.md` | 169 | yes |
| `deerflow_bridge/skills/actor-ontology-research/references/scoring-rubric.md` | 18 | yes |
| `deerflow_bridge/skills/forecast-visuals/SKILL.md` | 200 | yes |
| `deerflow_bridge/skills/forecast-visuals/references/chart-patterns.md` | 248 | yes |
| `deerflow_bridge/skills/forecast-visuals/scripts/render.py` | 2138 | yes |
| `deerflow_bridge/skills/.DS_Store`, `forecast-visuals/scripts/__pycache__/render.cpython-312.pyc` | — | no (gitignored, `.gitignore:2`, `.gitignore:14`) |
| `forecast-visuals/scripts/logs/**.json`, `forecast-visuals/scripts/.claude/data/sessions/*.json` | 108 | no (gitignored `.gitignore:61` `logs/`, `.gitignore:46` `.claude/`) — stray Claude Code hook logs, see Surprises |

All anchors below are `path:line` relative to the repo root. "MT" = `deerflow_bridge/market_tools.py`, "R" = `deerflow_bridge/skills/forecast-visuals/scripts/render.py`.

---

## Purpose & position in the pipeline

1. **`market_tools.py`** is a self-contained, config-reflected DeerFlow tool module that exposes exactly one agent tool, `prediction_market_search`, which queries Polymarket's public, keyless Gamma API (`https://gamma-api.polymarket.com/public-search`) for active markets and returns a filtered JSON snapshot (MT:1-21, MT:37, MT:262-271, MT:627-645). It is deployed next to `deer-flow/deerflow_research.py` and imported by bare module name through `config.yaml` `use: market_tools:prediction_market_search_tool` (`deerflow_bridge/config.yaml:826-828`; deployment list `backend/app/services/pipeline_orchestrator.py:1358-1361`, copy loop `pipeline_orchestrator.py:1533-1536`). It runs inside the **research stage** subprocess, only when the agent calls it. Its second job is provenance: each fresh, non-empty result is appended to `<DEERFLOW_RUN_ARTIFACT_DIR>/prediction_market_candidates.jsonl` (MT:51-59, MT:318-365) so the deterministic market finalizer can include markets the agent found mid-research (`deerflow_bridge/deerflow_research.py:15361-15405`).
2. **Skills** (`deerflow_bridge/skills/<name>/`) are four DeerFlow skill bundles (markdown contracts + lazy references, plus one script) that the orchestrator deploys verbatim into `deer-flow/skills/public/<name>/` (`deerflow_bridge/runtime_skill_sync.py:47-52`). They are prompt-level contracts for the **legacy DeerFlow agentic research engine**: the DeerFlow client is constrained to these four skills (`deerflow_research.py:16918-16928`) and prompts slash-activate `/deep-research` and `/actor-ontology-research` (e.g. `deerflow_research.py:4854`, `13189`). The default **v3 engine does not activate any slash skill** (`deerflow_research.py:16689-16694`; default `RESEARCH_ENGINE='v3'` at `backend/app/config.py:1187`) and its tool schema has only `web_search`/`web_fetch` (`deerflow_bridge/research_gateway.py:3310-3343`), so in default runs the skill prose and the `prediction_market_search` tool are mostly dormant; exceptions are (a) `final-dossier-contract.md`, which the bridge reads and injects into legacy synthesis prompts (`deerflow_research.py:518-572`), and (b) `render.py`, which both engines execute deterministically as a subprocess (`deerflow_research.py:15931-16010`, called from `deerflow_research.py:16299`, `17887`, and v3 `deerflow_bridge/linear_research.py:5550`).
3. **`render.py`** is the forecast-visuals bundled renderer: it reads the research run directory's structured artifacts (`timeline.json`, `quantitative.json`, `prediction_markets.json`, optional `actors.json`, `sources.json`, `meta.json`, fallback `charts_data.json`) and writes self-contained Plotly HTML + PNG charts under `<dir>/charts/` plus a merged `<dir>/charts.json` manifest (R:1-46, R:1986-2134). The bridge then embeds the PNGs into `research_report.md` as a "Visual Annex" (`deerflow_research.py:15891-15928`) and audits a visual contract (`deerflow_research.py:15828-15851`).

---

## Walkthrough (source order)

### A. `deerflow_bridge/market_tools.py`

**Module docstring (MT:1-21)** — Chinese. States: adapted from `drf2/config/market_tools.py`; config `use: market_tools:prediction_market_search_tool`; constraints: stdlib + `requests` only (lazy import, ImportError fallback), never imports `backend/app` or `deerflow.*`; degrade-safe (never raises to harness); `langchain` optional (tool var is `None` without it); env knobs `PREDICTION_MARKETS_MIN_VOLUME` (200), `_MAX` (20), `_MAX_PER_EVENT` (3), `_PER_QUERY` (8). Invalid values fall back to defaults.

**Constants (MT:37-64)**
- `POLYMARKET_BASE_URL = "https://gamma-api.polymarket.com"` (MT:37).
- `_TRANSIENT_STATUS = {429, 500, 502, 503, 504}` — retried once (MT:40).
- `DEFAULT_MIN_VOLUME=200.0`, `DEFAULT_PER_QUERY=8`, `DEFAULT_MAX_TOTAL=20`, `DEFAULT_MAX_PER_EVENT=3`, `DEFAULT_TIMEOUT=15.0` s, `DEFAULT_NEGATIVE_CACHE_TTL_SECONDS=30.0`, `DEFAULT_SINGLEFLIGHT_WAIT_SECONDS=35.0` (MT:43-49).
- `MARKET_CANDIDATES_FILENAME = "prediction_market_candidates.jsonl"` (MT:59); `_CAPTURE_LOCK` (threading.Lock, MT:60); `_QUERY_CACHE_LOCK` (MT:61); `_QUERY_CACHE` process-global `OrderedDict` LRU (MT:62); `_QUERY_INFLIGHT` dict of single-flight records (MT:63); `_QUERY_CACHE_MAX = 128` entries (MT:64).

**`_MarketTransportFailure(RuntimeError)` (MT:67-68)** — internal marker raised by the default fetcher when the provider response was not obtained or schema-invalid; caught per query in `snapshot_for_queries`.

**`_env_float(name, default)` / `_env_int(name, default)` (MT:71-86)** — read `os.environ[name]`, strip; empty → default; `ValueError/TypeError` → default. `_env_int` uses `int(raw)` so `"8.0"` → default.

**`_bounded_env_seconds(name, default, maximum)` (MT:89-94)** — `_env_float`, non-finite (`inf`/`nan`) → default, then clamps to `[0, maximum]`.

**`_coerce_float(v)` (MT:97-105)** — `float(v)`; NaN → `None`; errors → `None` (Gamma returns numeric strings like `"32970.32"`).

**`_as_list(v)` (MT:108-118)** — list passthrough; JSON string decoded if it yields a list; else `[]` (Gamma `outcomes`/`outcomePrices`/`clobTokenIds` are often JSON-encoded strings).

**`_yes_price(outcomes, prices)` (MT:121-130)** — requires equal-length non-empty lists; returns the price at the index whose outcome name case-insensitively equals `"yes"`; otherwise `None` (so non-binary/categorical markets without a "Yes" outcome are dropped downstream).

**`_market_url(event_slug, market_slug)` (MT:133-139)** — prefers `https://polymarket.com/event/{event_slug}`, else `.../market/{market_slug}`, else `""`.

**`_http_get(path, params, timeout=15.0)` (MT:142-167)** — lazy `import requests` (ImportError → log warning, return `None`, MT:144-148). Up to 2 attempts (MT:151): a transient status on attempt 1 → `continue` with no sleep/backoff (MT:155-157); `ConnectionError`/`Timeout` → `continue` (retried once, MT:160-162); any other exception (4xx via `raise_for_status`, JSON decode, a transient status on attempt 2) → `break` (MT:163-165). Returns parsed JSON or `None` after logging `Polymarket GET {path} 失败` (MT:166-167). Sends header `Accept: application/json`; no API key, no auth. Network side effect: HTTPS GET.

**`normalize_market(raw, matched_query, min_volume=200, event_title="", event_slug="")` (MT:170-228)** — returns a market record or `None`. Rejections, in order: non-dict; missing `id` or `question` (MT:182-185); `closed` is `True` or string `"true"` (MT:187-188; comment: `active` stays True on resolved markets so it is not trusted); Yes price missing or not strictly in `(0,1)` (MT:189-192); `volume < min_volume` (MT:195-196). Output keys: `market_id`, `exchange="polymarket"`, `question`, `implied_yes_prob` (rounded 4 dp), `volume`, `liquidity` (missing → 0.0), `event_title` (event title, else `groupItemTitle`), `matched_query`, `url`, `end_date` (raw `endDate`) (MT:197-208). Additive LOOP-017 fields, only when derivable (never fabricated): `outcomes` (MT:215-217), `outcome_prices` (only if every price parses, MT:218-220), `clob_token_ids` (MT:221-223), `clob_yes_token_id` = token at the "Yes" outcome index if that index is within the token list (MT:224-227; explicitly not index 0 because Gamma sometimes orders `["No","Yes"]`).

**`_cap_per_event(ranked, max_per_event, max_total)` (MT:231-246)** — input already volume-sorted. `max_per_event <= 0` → only truncate to `max_total` (MT:235-236). Otherwise keeps at most `max_per_event` markets per key = `event_title` or `market_id` (MT:240), then truncates to `max(0, max_total)` (MT:246).

**`snapshot_for_queries(queries, per_query=8, max_total=20, min_volume=200, max_per_event=3, fetch=None, diagnostics=None)` (MT:249-315)**
- `_default_fetch(q, limit)` (MT:262-271): `GET /public-search` with `q`, `limit_per_type=limit`, `events_status="active"`; `None` → raise `_MarketTransportFailure("...unavailable")`; response not a dict with a list `events` → raise `_MarketTransportFailure("...invalid response schema")`; returns the event list.
- `fetch` is injectable for tests (MT:273).
- For each non-blank query (MT:280-284): call fetch; any exception → `transport_failures += 1`, log, skip (MT:285-290); else `successful += 1`; for each dict event, read `title`/`slug`, for each raw market count `raw_candidate_count` (dicts only) and normalize; first-seen `market_id` wins (dedupe, MT:304-305).
- Ranks by descending `volume` (MT:306), fills `diagnostics` with `attempted_query_count`, `successful_query_count`, `transport_failure_count`, `raw_candidate_count`, `candidate_count` (= pre-cap `len(ranked)`, MT:307-314), returns `_cap_per_event(...)` (MT:315). Never raises for per-query failures.

**`_capture_market_candidates(queries, markets, status=None)` (MT:318-365)** — best-effort provenance append.
- No-op if no dict market (MT:327-328), if `DEERFLOW_RUN_ARTIFACT_DIR` unset/blank (MT:329-331), if its realpath is not an existing dir (MT:333-335), or if the realpath of `<root>/prediction_market_candidates.jsonl` escapes the root (symlink defense via `os.path.commonpath`, MT:336-338).
- Record: `{"captured_at": <UTC ISO>, "source": "polymarket", "queries": [...], "markets": [...], "status": {...}?}` (MT:339-346), compact JSON + `\n`, UTF-8.
- Records > 1,000,000 bytes are skipped with a warning (MT:350-352).
- Under `_CAPTURE_LOCK`, `os.open(O_WRONLY|O_CREAT|O_APPEND, 0o600)` and a short-write-safe write loop (MT:353-363). Any exception → warning, never raised (MT:364-365).

**`_reset_market_query_cache()` (MT:368-376)** — clears the LRU, sets every in-flight event (waking waiters, who then see no result → `inflight_timeout`), clears in-flight map. Used by tests.

**`_cached_snapshot(queries, *, per_query, max_total, min_volume, max_per_event) -> (markets, cache_hit, singleflight_shared, status)` (MT:379-529)**
- Key = (sorted casefolded stripped queries, per_query, max_total, min_volume, max_per_event) (MT:389-392). Query order is not part of the key.
- Under lock: cached entry with `expires_at` ≤ `time.monotonic()` is evicted (MT:396-401); a live hit is moved to MRU and returned as copies with `cache_hit=True` (MT:402-409). Otherwise, join an existing flight or create one and become the **owner** (MT:410-414).
- **Waiter path** (MT:416-446): waits `PREDICTION_MARKETS_SINGLEFLIGHT_WAIT_SECONDS` (default 35, clamp [0,120]); if the owner's `(markets, status)` tuple is present, return it with `singleflight_shared=True`; else return `[]` with status `state="inflight_timeout"`, `empty_reason="inflight_timeout"`, `inflight_timeout_count=len(queries)`.
- **Owner path** (MT:448-504): calls `snapshot_for_queries` with diagnostics; classifies: all queries failed → `transport_failure`; some failed → `partial_success` (if markets) or `partial_transport_failure`; no failures + markets → `success`; no failures + no markets → `verified_empty` with `empty_reason="no_equivalent_market"` (MT:465-478). Status dict keys: `state, attempted(True), attempted_query_count, query_count, successful_query_count, transport_failure_count, inflight_timeout_count(0), raw_candidate_count, candidate_count, empty_reason` (MT:479-490). An unexpected exception → `transport_failure` with `transport_failure_count=len(queries)` (MT:491-504).
- `finally` (owner only, MT:505-528): cache only when `transport_failure_count == 0` (MT:508); positive results get `expires_at=None` (no TTL, LRU-only); empty results get TTL `PREDICTION_MARKETS_NEGATIVE_CACHE_TTL_SECONDS` (default 30, clamp [0,3600]) (MT:510-517); LRU trimmed to 128 (MT:524-525); publish result to flight, drop in-flight entry, set event (MT:526-528).

**`prediction_market_search_impl(queries: str) -> str` (MT:532-616)** — pure-logic entry; returns JSON text, never raises.
- Splits on newlines then commas, strips, casefold-dedupes, keeps at most **6** queries (MT:539-552). No per-query word-count trimming.
- No queries → compact JSON `{"queries": [], "markets": [], "cache_hit": false, "singleflight_shared": false, "status": {"state": "no_queries", "attempted": false, ...}, "note": "no queries given"}` (MT:553-572).
- Otherwise `_cached_snapshot` with env knobs `PREDICTION_MARKETS_PER_QUERY` (8), `_MAX` (20), `_MIN_VOLUME` (200.0), `_MAX_PER_EVENT` (3) (MT:573-579).
- Capture to ledger only if not a cache hit and not single-flight shared (MT:580-581).
- `note` (MT:582-592): default caveat ("Machine-fetched snapshot... calibration anchors, not ground truth."); empty + `verified_empty` → prefixed "No active, liquid markets matched these queries."; empty + `transport_failure` → "Prediction-market provider unavailable; no absence conclusion was reached."; empty + `inflight_timeout` → "...still in flight..."; empty + `partial_transport_failure` → "...incomplete because some queries failed in transport."
- Returns indented JSON (`indent=2`, `ensure_ascii=False`) with keys `queries, markets, cache_hit, singleflight_shared, status, note` (MT:593-596).
- Last-resort `except Exception` → compact JSON with `markets: []`, `status.state="transport_failure"`, `transport_failure_count=1`, note `prediction market search unavailable: {e}`; this payload has **no `queries` key** (MT:597-616).

**LangChain tool (MT:619-648)** — `from langchain_core.tools import tool`; `@tool("prediction_market_search") def prediction_market_search_tool(queries: str) -> str` delegates to the impl (MT:624-645). The docstring is the LLM-facing tool description: up to 6 short phrases (≤~5 words) separated by newlines/commas; lists returned fields; instructs to inspect `status.state` (`verified_empty` = evidence of no liquid overlap; transport/in-flight = unknown) and "Never fabricate market prices" (MT:629-644). `ImportError` → `prediction_market_search_tool = None` (MT:647-648).

### B. `skills/prediction-markets/SKILL.md` (93 lines)

- Frontmatter (`:1-4`): name `prediction-markets`; triggers on any forecast/probability question; describes the tool and table output; "calibration anchors, never ground truth".
- Activation discipline (`:8-10`): if eagerly loaded, do not re-read SKILL.md from disk.
- §1 (`:12-41`): markets are money-weighted belief, not truth; workflow "fetch → filter → compare → explain divergence — never copy" (`:14`). Lists returned fields (`:16`). States every successful tool response is captured to `prediction_market_candidates.jsonl` and the deterministic finalizer relevance-gates/refreshes it into `prediction_markets.json` (`:18`); do not reissue identical payloads because the tool caches (`:18`). Fallback: `web_fetch` of `https://gamma-api.polymarket.com/public-search?q=<short query>&limit_per_type=8&events_status=active` (`:20-26`). Only two permitted access paths; no shell/CLI/wallet/CLOB order endpoint/state-changing operation (`:28-33`). **Stop rule** (`:35-41`): one full sweep in the opening pass; if no liquid relevant market, record `no_market_coverage` and stop; one refresh at final synthesis only; never loop retries on `transport_failure` within a phase.
- §2 Query craft (`:43-54`): query like market titles ("Ohio Senate winner", "House control 2026"); ≤5 words; derive up to ~6 queries from 2-3 salient noun phrases, up to 4 hot topics, top 2-3 actors; dedupe case-insensitively; change angle not word order; reuse exact `market_id`/`url`; record `end_date`, volume, liquidity, fetch timestamp.
- §3 Filtering (`:56-65`): restates the tool's own filters (closed/unpriced/0-1/volume<~200, dedupe, volume rank, ~3 per event); relevance is the agent's job; near-miss markets may be cited with the mismatch named.
- §4 (`:67-79`): "Prediction Market Signals" table columns `Market question | Implied P(yes) | Volume (USD) | Ends | URL` (`:71-73`) with freshness caveat; **divergence rule: >10 percentage points must be explained** (`:78`); re-fetch if stale.
- §5 (`:81-93`): failure-mode checklist (long NL queries, research-speak, keeping lexical false positives, closed/resolved anchors, copying price, silent >10pp divergence, mismatched threshold/date, fabrication, no freshness caveat, re-running after `no_market_coverage`, retrying transport failures).

### C. `skills/deep-research/` (core + two lazy references)

**SKILL.md (95 lines)**
- Frontmatter (`:1-4`): always-on core for KIQ decomposition, source grading, evidence-yield stopping, disconfirmation, forecast inputs, provenance, phase-aware handoffs.
- Activation discipline (`:10-13`): never reread SKILL.md; load only named lazy references.
- **Phase type** (`:15-23`): *Working phases* (opening notes, scoped workers, top-ups, verification, actor passes, corrections, fan-out absorption) are exempt from any final word/section floor; *Final dossier synthesis only* uses `references/final-dossier-contract.md`; *Structured extraction/judging* follows the requested schema. Rationale: a global floor multiplies latency/tokens.
- Core loop (`:25-32`): 3-7 KIQs; search documents; `prediction_market_search` once in opening pass (fallback read-only `web_fetch` to Gamma), `no_market_coverage` stop rule, no same-phase retry of a transport-failing market tool (`:28`); evidence ledger `KIQ → claim → source/title/real URL/date/tier → independence → grade → open gap` (`:29`); convergence check after each evidence-bearing call (`:31`).
- Evidence discipline (`:34-47`): S1–S4 definitions (S4 = reject, do not fetch or cite) (`:36-39`); only cite fetched sources, never invent title/URL/market/quote/future-dated doc; repeated outlets = one origin (`:41`); per-number record (`:43`).
- KIQ/evidence-yield stopping (`:49-58`): tool/source counts are telemetry not quotas; "KIQ done" = B2-or-better + opposing case checked, or paths exhausted with explicit gap; yield stop after two genuinely different angles produce no delta; no near-duplicate queries; checkpoint ledger each pass.
- Forecast-specific requirements (`:60-74`): base rates, actors, typed relationships, drivers, timeline, scenarios, indicators, chart-ready tables, market fields (question, ID, P(yes), volume/liquidity, end date, URL, fetch time).
- Synthesis gate (`:76-87`) and final routing (`:89-95`).

**references/final-dossier-contract.md (66 lines, 5,692 bytes)** — Load only on explicit final synthesis (`:3`). Deep final dossier: **10,000-word evidence-dense floor**, no maximum (`:7`). Required 13-part structure (`:13-25`), incl. cast-wide actor intelligence (`:17`) and Prediction Market Signals (`:22`). Citation contract: preserve deterministic `[S<n>]` markers, never invent; calibrated-language bands (almost certain >90%, likely 65–85%, roughly even 45–55%, unlikely 15–35%, remote <10%) (`:31-36`). Chart-ready handoff tables feeding `actors.json`, `sources.json`, `quantitative.json`, `timeline.json`, `contested.json`, market artifacts, charts (`:40-51`). Final self-check incl. "one canonical scenario partition" (`:53-66`). The bridge injects this file (capped at 12,000 chars) into legacy synthesis prompts (`deerflow_research.py:518-572`, used at `5231`, `6151`, `6175`).

**references/source-tradecraft.md (73 lines)** — research design per claim type (`:5-7`); search craft (document targeting, `site:`, `filetype:pdf`, pivots, Wayback) (`:9-15`); domain source map table (`:17-27`); pre-fetch screen (2+ red flags ≈ S4) (`:31-33`); evidence ledger example + Admiralty shorthand (load-bearing ≥ B2) (`:35-46`); verification checklist (`:48-56`); adversarial analysis (ACH-lite, key assumptions, disconfirmation, premortem, consensus check) (`:58-64`); obstacle routing ("Tool failure/empty page: one changed-approach retry") (`:66-73`).

### D. `skills/actor-ontology-research/` (core + two lazy references)

**SKILL.md (215 lines, 19,465 bytes; test cap <20,000 bytes at `backend/tests/test_sessionb_skill_hygiene.py:64-67`)**
- Frontmatter (`:1-12`); do not reread SKILL.md (`:16`); dossier caps quality of every later stage (`:18`); defers to `deep-research` evidence discipline on conflict (`:20`).
- §1 Mission + six principles (`:22-35`): actors are the spine; rank by causal role; depth over breadth ("Twelve deeply-profiled actors beat forty thin ones"); relationships first-class; time as a dimension; evidence discipline with "≤2 attempts" anti-thrashing. Writing may not begin before the judge gate passes (`:35`).
- §2 Triage (`:37-65`): ACTOR vs SOURCE vs CONTEXT OBJECT (`:43-47`); reporter/outlet rule (`:49`); role-classes principal/arbiter/stakeholder/amplifier/intermediary (`:53-59`); salience signals + tier (`:63`); cast hard-capped ~8–20 and never above `ACTOR_CAST_MAX` (default 20) (`:65`; config default `backend/app/config.py:1362`).
- §3 Per-actor dossier standard (`:67-90`): canonical name + aliases (sole entity-resolution signal) (`:72`), values/incentives/constraints/forward behavior/stance (`:77-82`), history, relational roster, evidence. §3.1 runtime role-contract handoff (`:92-100`): declarative evidence only, never imperatives (runtime treats dossier prose as untrusted); sources/context objects never get an agent role.
- §4 Edge contract (`:102-120`): direction, canonical type vocabulary (Alignment/Antagonism/Governance/Economic/Dependency/Information), valence (allied/adversarial/neutral/transactional), strength, basis, mechanism.
- §5 History & evolution (`:122-132`).
- §6 Multipass workflow Pass 0–4 + budget split ¼/½/¼ (`:134-148`).
- §7 AI-judge loop (`:150-161`): score 0-5, PASS/FAIL, targeted gap list, surgical refinement, re-judge, cap **3 refinement rounds**; explicit final FAIL ⇒ dossier unusable; judge transport/parse failure may degrade only if deterministic coverage ledger passes.
- §8 Rubric (`:163-182`): 10 dimensions; pass bar: no dimension <3, dims 1,3,4,6,8,9,10 ≥4, mean ≥4; `ACTOR_DOSSIER_JUDGE_STRICT` requires all ≥4. This matches code `_JUDGE_CRITICAL` (`deerflow_research.py:13908-13911`) and `dossier_passes` (`deerflow_research.py:14027-14045`).
- §9 Output contract (`:184-197`): `### Actor: <canonical name>` headings, edges as `Source —[TYPE, valence, strength]→ Target — basis`, and exactly one `ACTOR_INTELLIGENCE_LEDGER_V1` (parsed by regex at `pipeline_orchestrator.py:238` and `deerflow_research.py:13345`).
- §10/§11 downstream map + failure checklist (`:199-215`); cites "root `CLAUDE_ONTOLOGY.md`" (`:205`) which does not exist (Surprises).

**references/actor-intelligence-contract.md (169 lines)** — 17 required dimensions (`:10-28`); claim contract (`evidence_type` enum, `claim_valid_at`/`horizon`/`status`, `source_support` rows with exact `supporting_quote`, `supporting_span`, producer `receipt_id`, 64-char `content_sha256`, `source_publication_date`; controlled `visibility` vocabulary; boolean `actor_knows`) (`:33-56`); epistemic separations (`:58-70`); forward-behavior evidence and a bounded cast-wide completion pass (≤2 distinct source attempts per unsupported dimension) (`:72-94`); structured gap object (`reason, attempted_queries, receipt_ids, result_ids, attempt_count, exhausted`) with receipt hash-binding rules (`:96-119`); relationship evidence (`:121-128`); coverage ledger `actor-intelligence/v1` (`:130-144`); runtime handoff to `actors[].intelligence.dimensions` and `actor-role/v2` (`:146-154`); two extra critical judge dimensions (`:156-169`).

**references/scoring-rubric.md (18 lines)** — 5/5 vs ≤2 anchors for the 10 rubric dimensions (`:7-18`).

### E. `skills/forecast-visuals/` (contract + renderer)

**SKILL.md (200 lines)** — five-check gate (decision relevance, actual rows, comparability, provenance, honest uncertainty) (`:23-38`); input artifacts and fields (`:45-61`); run snippet locating `render.py` under `/mnt/skills` or `.` and using `${RESEARCH_CHARTS_PYTHON:-python3}` (`:63-69`); `--context` / `--diagnostics` opt-ins (`:71-74`); reader-facing outputs table (`:86-92`); quant/trajectory/revision contracts (`:94-139`); diagnostics off by default (`:141-158`); embed-at-point-of-use rule and table fallback, "Do not emit Mermaid" (`:160-177`); manifest checks; exit codes `0/2/3` (`:179-200`).

**references/chart-patterns.md (248 lines)** — selection matrix of reader question → data contract → view → check (`:7-25`); EV, grid storage, humanoid robotics, AI compute examples (`:27-120`); technology cost, forecast revision, policy timeline, scenario/binary, concentration, consumer structure, technical-route, supply-demand, sensitivity patterns (`:122-220`); anti-pattern table (`:222-237`); final visual QA (`:239-248`). Contains one threshold that contradicts code (see Surprises).

**`scripts/render.py` (2138 lines)** — section by section:

- **Docstring (R:1-46)**: inputs, outputs (`charts/<id>.{html,png}`), design constraints (skip missing artifacts, per-chart try/except [verifier: only the `renderer(...)` call is wrapped (R:2099-2103); every `prep_*` runs eagerly while the `jobs` list is built (R:2057-2093), outside any try, so a prep exception aborts the whole script (R:2057-2093, R:2099-2103)], WAVE9 theme, self-contained HTML, PNG degrade ladder kaleido→matplotlib→HTML-only, plotly missing → matplotlib-only PNG, both missing → exit 3, locked atomic manifest merge), exit codes.
- **Imports / capability detection (R:48-87)**: optional `fcntl` (R:63-66); `plotly.graph_objects` + `make_subplots` → `_HAS_PLOTLY` (R:71-78); `matplotlib` with `Agg` backend → `_HAS_MPL` (R:80-87).
- **WAVE9 theme block (R:89-127)**: copied verbatim from `backend/app/services/report_visualizer.py` (source of truth; constants verified identical at `report_visualizer.py:228-245`). `_PALETTE` 8 CVD-safe colors (R:104-105), `_SEQ_BLUES` (R:106), `_COLOR_MODEL` `#2a78d6`, `_COLOR_MARKET`, `_COLOR_POS/NEG/NEU`, `_COLOR_STALE`, `_COLOR_GOOD`, `_SURFACE #fcfcfb`, `_GRID`, `_AXIS`, `_INK`, `_INK_2` (R:107-118); legend top-right (R:121-122); `_COLOR_OBSERVED = blue`, `_COLOR_FORECAST = amber _PALETTE[2]` (R:126-127).
- **`_apply_wave9_layout(fig, title, height=None, **kwargs)` (R:130-149)**: title/font/background/colorway/margins/hover font; kwargs override; grid/axis colors on all axes.
- **`_mpl_finalize(f, path)` (R:152-162)**: surface background, axis colors, `tight_layout`, `savefig`, close.
- **Role/edge maps (R:165-186)**: `_ROLE_COLORS` principal/arbiter/stakeholder/amplifier/intermediary (R:168-174), fallback neutral (R:175); `_EDGE_COLORS` adversarial/cooperative/governance (R:177-181); `_LEVEL_WEIGHT` ordinal tiers very high=4 … very low=0.5 (R:183-186).
- **`_OWNED_CHART_IDS` (R:190-198)**: `actor_network, timeline, quant_metrics, metric_trajectories, forecast_revisions, market_probabilities, source_quality` — the only manifest rows this renderer may replace.
- **Utilities (R:199-255)**: `_env_truthy` (1/true/yes/on, R:199-201); `_log` → stderr prefixed `[render]` (R:204-205); `_read_json` (OSError/ValueError → None, R:208-212); `_atomic_write` (mkstemp in same dir, fsync, `os.replace`, cleanup, R:215-228); `_num` first number in a value string (strips commas; bool rejected; NaN → None) (R:231-241); `_num_range` explicit `a–b`/`a-b`/`a~b`/`a to b` range → (min,max) (R:244-255).
- **Comparability vocab (R:258-338)**: unit aliases (R:258-266), ambiguous units rejected for comparisons (`%`, `units`, `usd billion`…, R:267-271), forecast-signal regex (R:272-277), internal-forecast-source regex (`internal|dossier|synthesis|working assumption|analyst interpolation|our estimate|内部推演|本报告|分析师插值`, R:278-282), denominator / time-basis / measure-family patterns (R:283-317), subject stopwords (R:318-328), revision noise words (R:329-334), generic source words (R:335-337), `_TIER_RANK` S1..S4 (R:338).
- **`_canonical_unit` / `_comparable_unit` (R:341-357)**: comparable iff non-empty, not `date`, not ambiguous; `%` units need ≥3 extra chars (e.g. `% new car sales`); otherwise requires `per`, `/`, `of`, or an energy/mass/barrel/credit/bps unit regex.
- **`_is_projection(row)` (R:360-374)**: explicit `is_projection` bool → `is_actual` bool → label in `value_type/observation_type/fact_type/status` (`actual|historical|observed|reported` vs `forecast|…|target|expected`) → forecast-signal regex over `metric`+`definition`.
- **Text helpers (R:377-405)**: `_truncate` with `…`; `_plotly_text` converts `US$`/bare `$` to `USD ` then HTML-escapes (prevents Plotly MathJax) (R:382-393); `_parse_date` extracts the first `YYYY-MM-DD` (no wall clock) (R:396-405).
- **Quant grouping helpers (R:408-534)**: denominator key from unit (margin→revenue; pattern labels; text after `per` or `/`) (R:408-419); `%` units reconcile definition denominators — conflicting markers → `None` (row dropped) (R:422-434); time basis from explicit period fields else regex labels else `"as-of"` (R:437-453); measure family first-match label else normalized definition (R:456-461); subject tokens with EV synonym folding and year removal (R:464-476); `_split_quant_families` greedy subject-token clustering keeping clusters of ≥2 rows (R:479-491); `_quant_panel_subject` builds titles "Current …", "<year> … targets", "… forecasts / targets" (R:494-534).
- **Revision/source identity helpers (R:537-607)**: `_source_outlook_family` normalizes BNEF aliases, `Electric Vehicle Outlook`→`evo`, strips citations `[..]`/`【..】` and years, empty if only generic words (R:537-556); `_revision_target_year` = the single non-vintage year in name+definition, else None (R:559-562); `_revision_identity_text` truncates at causal words (`post|after|following|due to|because of|in response to`), removes vintage/target years, noise and publisher tokens (R:565-590); `_source_identity` canonical URL (lowercased scheme/host, path case kept, trailing `/` and fragment dropped) else lowercased title (R:593-607).
- **`prep_network(actors_obj, max_nodes=30)` (R:615-733)**: requires dict with ≥1 named actor; influence = first explicit numeric (`influence_score`, `salience_score`, `salience.score`, numeric `influence`) else ordinal tier via `_LEVEL_WEIGHT` else 1.0 (R:628-647); keep top `max(2,max_nodes)` (R:649); alias map from names, `aliases`, and a parenthetical-stripped prefix, only unambiguous keys (R:655-670); deterministic circle layout grouped by sorted `role_class` (R:671-679); node size `14 + 26*infl/max` (R:688); edges: endpoints resolved via alias map, self-loops dropped, `(src,tgt,TYPE)` deduped, semantic class from `valence`/`sign`, `REGULATES/GOVERNS/ENFORCES`, or numeric `polarity` ±0.15 (R:695-730); returns None if no edges and <3 nodes (R:731-732).
- **`prep_timeline(rows, max_events=40)` (R:736-786)**: rows with non-empty `date` and `event`; dedupe via `set`, sort by raw date **string**, keep the last 40 (R:753-755); 6 visual lanes, a lane is reusable after ≥30 days (ISO dates only) (R:756-778); point = `index, date, lane, label (≤90 chars), full`.
- **`prep_quant(rows, max_bars=10, max_panels=3)` (R:789-875)**: value = midpoint of explicit range, else `value_num`, else first number in `value` (R:801-806); drop rows lacking metric, comparable unit, `source`, `definition`, parseable `as_of_date` (R:807-815); drop **non-projection rows with negative `staleness_days`** (future-dated actuals) (R:816-819); drop if denominator/measure family/subjects unresolved (R:820-827); group key `(unit, exact as_of ISO date, time_basis, denominator, measure_family)` (R:828); split each group into subject families (R:844-846); panels sorted by size desc then key, top 3 (R:849-851); within panel sorted by tier, stale, projection, input index; top 10 bars; bar label `metric (as of YYYY-MM-DD)` ≤72 chars (R:852-867). Output `{"panels":[{unit,title,as_of,time_basis,bars:[{metric,value,value_label,low,high,unit,as_of,tier,source,definition,projection,stale,idx,label}]}]}`.
- **Trajectory helpers (R:878-1009)**: series-name folding (removes years/actual/forecast/qN/hN/fy) (R:878-900); region aliases (US/China/Europe/India/Global) (R:904-920; blank → "Global"); unit bucket `percent` vs lowercased unit (R:923-927); `_trajectory_year` = canonical `year` (1900–2100) → `period_end`/`target_date` → nested `period.period_end|end` → (projections only) latest 20xx year in metric/series text (R:930-952); family = `metric_family` else folded series (R:955-962); value = `value_num` else `_num(value)` (R:965-970); forecast flag = `value_kind` else `_is_projection` (R:973-983); `_trajectory_row_is_publishable` requires source (or `analyst`), definition, parseable `as_of_date`; forecasts additionally need an `http(s)` `source_url` with a host and no internal-source regex hit (R:986-1009).
- **`prep_trajectories(rows, max_series=4)` (R:1012-1093)**: group key `(family, region, technology, unit bucket)` (R:1058); one point per year — best tier wins, ties keep first (R:1080-1085); a series qualifies with **≥3 distinct years** (R:1088-1091); sort by point count desc then name; top 4.
- **`prep_revisions(rows, max_series=3)` (R:1096-1180)**: metric must end with `(20YY)` (R:1102-1105) and contain a forecast signal (R:1106-1108); requires value, unit, source, definition, as_of; vintage year must equal `as_of` year (R:1117-1119); requires non-empty publisher family and a single target year (R:1120-1123); key `(publisher_family, target_year, unit, metric identity, definition identity)` (R:1138-1144); best tier per vintage; series needs ≥3 vintages (R:1171); top 3.
- **`prep_markets(payload, max_bars=12)` (R:1183-1230)**: accepts `{"as_of","markets":[...]}` or a bare list; probability from `implied_yes_prob` | `yes_probability` | `probability`; values in (1,100] are divided by 100 (R:1202-1203); keeps strictly `0<p<1`; identity `market_id` or question (lowercased); keeps the higher `(volume, question)` duplicate (R:1217-1221); top 12 by volume then reversed so the most liquid draws at the top (R:1225-1229).
- **`prep_sources(payload, run_anchor=None)` (R:1233-1325)**: dedupe by `_source_identity`; date from `date|publication_date|published_at|as_of_date`; reference date priority: `meta.json finished_at` ("run_metadata") → modal `date + staleness_days` ("explicit_staleness_anchor") → latest dated source → none (R:1264-1284); tier buckets S1–S4/Untiered (R:1293-1294); freshness buckets ≤30, 31–90, 91–365, >365 days, Undated (R:1286, R:1299-1314).
- **HTML/PNG output (R:1333-1416)**: `_EMBEDDED_FAVICON` inline SVG data URI (R:1333-1338); `_document_title` = plain-text figure title or stem title-cased (R:1341-1349); `_finalize_html_document` inserts `<title>` + `<link rel=icon>` before `</head>` (R:1352-1360); `_write_outputs(fig, mpl_draw, charts_dir, stem)` (R:1363-1416): with plotly, `write_html(include_plotlyjs=True, full_html=True, div_id="forecast-visual-<stem>")`, re-read, add metadata, strip trailing spaces per line preserving final newline, rewrite if changed (R:1373-1393); PNG via `fig.write_image` (kaleido) with width clamp [800,1800] (default 1200), height clamp [420,1800] (default 750), `scale=2` (R:1396-1406); on failure or no plotly, matplotlib `mpl_draw` (R:1409-1415). Returns `(png_rel, html_rel)` as `charts/<stem>.<ext>`.
- **Renderers (R:1419-1905)** — each builds a plotly fig (if available) and a matplotlib fallback, then `_write_outputs`:
  - `render_network` → `actor_network`: edge line traces with hover labels + node markers/text, axes hidden (R:1419-1454).
  - `render_timeline` → `timeline`: numbered markers at (raw date, lane), hover with escaped date/full text, numbered key as paper annotations in 1 or 2 columns (2 if >14 events), height `max(620, 430+28*rows)` (R:1457-1504). Matplotlib fallback uses index positions, not dates (R:1490-1502).
  - `render_quant` → `quant_metrics`: one subplot row per panel, **`shared_xaxes=True`** (R:1512-1522); per panel two traces (observed circles blue, forecast diamonds amber) with stale `⚠` marker and red outline, asymmetric error bars only when a range exists, escaped hover (metric, value, as-of, definition, source) (R:1524-1570); title "Comparable Forecast Benchmarks" with subtitle (R:1571-1577).
  - `render_trajectories` → `metric_trajectories`: one row per series; observed solid line+circles, forecasts dashed+diamonds; x = integer year with `dtick=1`, hover includes period end, as-of, definition, source, URL (R:1609-1710).
  - `render_revisions` → `forecast_revisions`: one row per series, x = vintage, labeled values (R:1713-1771).
  - `render_markets` → `market_probabilities`: horizontal bar of P(yes)% with sequential blue colorscale 0–100, `customdata` volume/liquidity/market_id/end_date, dotted 50% line, title suffixed "(as of YYYY-MM-DD)" (R:1774-1828).
  - `render_sources` → `source_quality`: two horizontal bar panels (tier, freshness) with a note explaining the freshness anchor (R:1831-1905).
- **Manifest (R:1908-1983)**: `_owned_chart_id` — explicit `id` is authoritative (owned only if in `_OWNED_CHART_IDS`); id-less legacy rows owned only if `path|html_path|png_path` stem is an owned id; `source_data` is never ownership evidence (R:1908-1930). `_merge_manifest` keeps all non-owned rows in order, drops **all** owned rows, appends this run's entries in fixed `_OWNED_CHART_IDS` order, last duplicate wins (R:1933-1957). [verifier: it keeps only non-owned *dict* rows. Non-dict list items are dropped, and a charts.json that is unreadable or not a JSON list counts as empty, so its foreign rows are overwritten (R:1941-1942, R:208-212). The `flock` is skipped when `fcntl` cannot be imported (R:63-66, R:1966-1967)] `_manifest_update_lock` uses `charts.json.lock` + `fcntl.flock(LOCK_EX)` (R:1960-1972). `_update_manifest` = lock → merge → `_atomic_write` (R:1975-1983).
- **`main()` (R:1986-2134)**: argparse `--dir` (default `.`), `--context`, `--diagnostics` (R:1987-2016); env `RESEARCH_CHARTS_INCLUDE_DIAGNOSTICS` / `RESEARCH_CHARTS_INCLUDE_CONTEXT` (R:2019-2024); no plotly and no matplotlib → log and **return 3** (R:2025-2030); `mkdir <dir>/charts` (R:2032-2034); load artifacts with `charts_data.json` fallback per artifact (R:2036-2053); `meta.json.finished_at` as run anchor (R:2054-2055). Default jobs: `timeline`, `quant_metrics`, `metric_trajectories`, `forecast_revisions`, `market_probabilities` (all `data_class="forecast_domain"`) (R:2057-2077); `actor_network` (`context`) prepended only with context opt-in (R:2078-2084); `source_quality` (`diagnostic`) appended only with diagnostics opt-in (R:2087-2093). Per job: empty prep → log skip; renderer exception → log and continue; entry `{id, title, caption, source_data, data_class, path(png preferred), html_path (only when both)}` (R:2094-2118). Manifest written if any entry or a manifest already exists (cleanup of stale owned rows) (R:2120-2126). **No entries → return 2** (even after cleanup) (R:2127-2132); else return 0 (R:2133-2134). [verifier: an uncaught exception exits 1 with a traceback. Sources include a `prep_*` error (e.g. a `quantitative.json` row with `"year": NaN` raises ValueError at `int(y)` in `_trajectory_year`, R:937; reproduced in memory), a `charts/` mkdir failure, and a manifest I/O or lock error (R:2034, R:2123-2124). On a prep error no manifest cleanup happens. The bridge treats any non-zero code as "skip" (`deerflow_research.py:15976-15980`)]

---

## Control flow

### Market tool (legacy DeerFlow engine)

1. Orchestrator syncs `deerflow_bridge/market_tools.py` into `deer-flow/` next to the deployed script (`pipeline_orchestrator.py:1358-1361`, `1533-1536`).
2. Orchestrator builds the research subprocess env: `PREDICTION_MARKETS_ENABLED/MAX/MIN_VOLUME/MAX_PER_EVENT/PER_QUERY/MIN_RELEVANCE` from `Config` (`pipeline_orchestrator.py:2358-2365`) and `DEERFLOW_RUN_ARTIFACT_DIR = realpath(handoff_dir)` (`pipeline_orchestrator.py:2374-2378`).
3. DeerFlow reflection loads `market_tools:prediction_market_search_tool` from `config.yaml:826-828`; the `scoped-researcher` subagent whitelists it with skills `deep-research` + `prediction-markets` (`config.yaml:1215-1223`).
4. Agent call → `prediction_market_search_tool(queries)` (MT:628) → `prediction_market_search_impl` (MT:532) → parse ≤6 queries → `_cached_snapshot` (MT:379) → owner: `snapshot_for_queries` (MT:249) → per query `_default_fetch` → `_http_get("/public-search")` (MT:142) → `normalize_market` per raw market (MT:170) → dedupe/rank/`_cap_per_event` (MT:231) → status classification → cache/publish → `_capture_market_candidates` (MT:318) when fresh → JSON string to agent.
5. Post-research deterministic finalization reads the ledger: `_load_tool_market_candidates` (`deerflow_research.py:15361-15405`) inside `_collect_prediction_markets` (`deerflow_research.py:15476`), which tags rows `captured_via="prediction_market_search"`; the orchestrator also globs per-track ledgers (`pipeline_orchestrator.py:10890-10897`, `11451`, `11481`) and lists the ledger as an artifact (`pipeline_orchestrator.py:9519-9520`).

### Skills

1. `runtime_skill_sync.py` hashes and atomically deploys the four bundles into `deer-flow/skills/public/` (`runtime_skill_sync.py:1-19`, `47-52`, `110-170`); the research child verifies provenance via `DRF_RUNTIME_SKILL_SYNC` (`deerflow_research.py:480-515`).
2. Legacy engine: `DeerFlowClient(available_skills={4 skills})` (`deerflow_research.py:16918-16928`); prompts slash-activate `/deep-research` (e.g. `deerflow_research.py:4854`, `4920`, `10434`) and `/actor-ontology-research` (`deerflow_research.py:13189`, `13314`, `14069`); `skill_activation_estimate` measures SKILL.md size for telemetry (`deerflow_research.py:445-477`); `final-dossier-contract.md` is read and injected into synthesis prompts (`deerflow_research.py:518-572`).
3. v3 engine: records `activated=False, reason="v3 engine uses its own static system prompt; no slash skill activation"` (`deerflow_research.py:16689-16694`).

### Renderer

1. Both engines call `_render_research_charts(out_dir, meta, plog, question)` (`deerflow_research.py:16299`, `17887`; v3 `linear_research.py:5550`), after `_collect_prediction_markets` (`deerflow_research.py:16291`, `17876`; v3 `linear_research.py:5548`).
2. If `RESEARCH_CHARTS_MIN <= 0`, rendering is skipped (`deerflow_research.py:4656-4666`, `15945-15949`).
3. Locates `render.py` under `skills/forecast-visuals/` or `skills/public/forecast-visuals/` (`deerflow_research.py:15952-15956`), runs `subprocess.run([py, render.py, "--dir", out_dir], timeout=RESEARCH_CHARTS_TIMEOUT)` with `py` from `_charts_python` (`RESEARCH_CHARTS_PYTHON` → `backend/.venv/bin/python` → `sys.executable`) (`deerflow_research.py:15863-15873`, `15966-15969`).
4. `render.py main()` (R:1986) → prep_* → render_* → `_write_outputs` → `_update_manifest`.
5. Non-zero exit (2 or 3) → warn and skip embedding (`deerflow_research.py:15976-15980`); else read `charts.json`, run `_visual_contract_audit` (`deerflow_research.py:15828-15851`), and `embed_chart_refs` adds a `## Visual Annex` excluding diagnostic charts (`deerflow_research.py:15891-15928`, `16014`).
6. An agent may also run the renderer itself via host bash (`config.yaml:1025-1036` `allow_host_bash: true`) using the SKILL.md snippet (`skills/forecast-visuals/SKILL.md:63-69`).

---

## Data & artifacts

| Artifact | Producer/consumer in slice | Format & key fields | Anchor |
|---|---|---|---|
| `<DEERFLOW_RUN_ARTIFACT_DIR>/prediction_market_candidates.jsonl` | written by MT | append-only JSONL, mode 0600; one line per fresh non-empty tool result: `captured_at` (UTC ISO), `source="polymarket"`, `queries[]`, `markets[]` (normalized records), optional `status{}`; lines >1 MB skipped | MT:339-363 |
| Tool response (string) | MT → agent | JSON: `queries, markets[], cache_hit, singleflight_shared, status{state, attempted, attempted_query_count, query_count, successful_query_count, transport_failure_count, inflight_timeout_count, raw_candidate_count, candidate_count, empty_reason}, note` | MT:593-596 |
| Normalized market record | MT | `market_id, exchange, question, implied_yes_prob, volume, liquidity, event_title, matched_query, url, end_date` + optional `outcomes, outcome_prices, clob_token_ids, clob_yes_token_id` | MT:197-227 |
| `_QUERY_CACHE` / `_QUERY_INFLIGHT` | MT in-memory | key `(sorted casefolded queries, per_query, max_total, min_volume, max_per_event)`; value `{markets, status, expires_at}`; flight `{event, result}` | MT:62-63, MT:389-392, MT:518-522 |
| `<dir>/timeline.json` | read by R | list of `{date, event}` | R:2042-2044, R:743-749 |
| `<dir>/quantitative.json` | read by R | list of rows: `metric, value, value_num, unit, source, source_url, definition, as_of_date, tier, staleness_days, is_stale, is_projection/is_actual/value_type/value_kind, period{…}/period_end/target_date, series, metric_family, region/geography, technology/technology_route, year, analyst` | R:2045-2047, R:789-843, R:930-1085 |
| `<dir>/prediction_markets.json` | read by R | `{as_of, markets:[{question|title, implied_yes_prob|yes_probability|probability, volume, liquidity, market_id, end_date}]}` or list | R:2048-2050, R:1183-1230 |
| `<dir>/actors.json` | read by R (context only) | `{actors:[{name, aliases, role_class, salience{tier,score}, influence_score, ...}], relationships:[{source, target, type, valence|sign, polarity}]}` | R:2038-2041, R:615-733 |
| `<dir>/sources.json` | read by R (diagnostics only) | list or `{sources:[{url, title, tier, date|publication_date|published_at|as_of_date, staleness_days}]}` | R:2051-2053, R:1233-1325 |
| `<dir>/meta.json` | read by R | `finished_at` used as freshness anchor | R:2054-2055 |
| `<dir>/charts_data.json` | read by R (fallback) | `{actors, relationships, timeline, quantitative, prediction_markets, sources}` | R:2037-2053 |
| `<dir>/charts/<id>.html` | written by R | self-contained Plotly (plotly.js inline), `<title>`, data-URI favicon, trailing whitespace stripped | R:1372-1393 |
| `<dir>/charts/<id>.png` | written by R | kaleido (scale 2) or matplotlib (dpi 160) | R:1396-1415 |
| `<dir>/charts.json` (+ `charts.json.lock`) | written by R | JSON list of `{id, title, caption, source_data, data_class, path, html_path?}`; foreign rows preserved | R:2107-2117, R:1933-1983 |

Chart IDs and source artifacts: `timeline`←timeline.json; `quant_metrics`, `metric_trajectories`, `forecast_revisions`←quantitative.json; `market_probabilities`←prediction_markets.json; `actor_network`←actors.json (opt-in); `source_quality`←sources.json (opt-in) (R:2057-2093).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `PREDICTION_MARKETS_PER_QUERY` | 8 in MT; **15** in `Config` and passed by orchestrator | Gamma `limit_per_type` per query | MT:44, MT:575; `backend/app/config.py:1434`; `pipeline_orchestrator.py:2363` |
| `PREDICTION_MARKETS_MAX` | 20 | cap on returned markets | MT:45, MT:576; `pipeline_orchestrator.py:2360` |
| `PREDICTION_MARKETS_MIN_VOLUME` | 200.0 | minimum volume for a market to be kept | MT:43, MT:577; `pipeline_orchestrator.py:2361` |
| `PREDICTION_MARKETS_MAX_PER_EVENT` | 3 (≤0 = unlimited) | per-event diversity cap | MT:46, MT:578, MT:235 |
| `PREDICTION_MARKETS_NEGATIVE_CACHE_TTL_SECONDS` | 30 (clamp 0–3600) | TTL of cached `verified_empty` results | MT:48, MT:512-517 |
| `PREDICTION_MARKETS_SINGLEFLIGHT_WAIT_SECONDS` | 35 (clamp 0–120) | how long an identical concurrent call waits for the owner | MT:49, MT:420-425 |
| `DEERFLOW_RUN_ARTIFACT_DIR` | unset (capture off) | root for the candidate ledger | MT:329; set at `pipeline_orchestrator.py:2378` |
| `PREDICTION_MARKETS_ENABLED` | true | **not read by MT** (only the deterministic collector honors it) [verifier: the legacy pre-pass market snapshot also checks it (`deerflow_research.py:16970-16974`), so two deterministic paths honor it; only the agent tool ignores it] | `deerflow_research.py:15484`; absent from MT |
| `RESEARCH_CHARTS_INCLUDE_CONTEXT` | off | adds `actor_network` | R:2022-2024 |
| `RESEARCH_CHARTS_INCLUDE_DIAGNOSTICS` | off | adds `source_quality` | R:2019-2021 |
| CLI `--dir` / `--context` / `--diagnostics` | `.` / off / off | run dir and opt-ins | R:1988-2015 |
| `RESEARCH_CHARTS_PYTHON` | unset | interpreter for render.py (skill snippet; bridge) | `forecast-visuals/SKILL.md:67`; `deerflow_research.py:15867`; `config.py:1467` |
| `RESEARCH_CHARTS_TIMEOUT` (bridge) | 180 s | render subprocess timeout | `deerflow_research.py:15854-15860` |
| `RESEARCH_CHARTS_MIN` (bridge) | 3 (0 disables rendering) | minimum decision charts when brief requests visuals | `deerflow_research.py:4656-4666` |
| `ACTOR_CAST_MAX` (skill-referenced) | 20 | cast cap | `actor-ontology-research/SKILL.md:65`; `config.py:1362` |
| `ACTOR_DOSSIER_JUDGE_STRICT` (skill-referenced) | false | all judge dimensions ≥4 | `actor-ontology-research/SKILL.md:182`; `deerflow_research.py:14035` |

---

## External calls

| Call | Details | Anchor |
|---|---|---|
| HTTPS GET Polymarket Gamma `/public-search` | params `q`, `limit_per_type`, `events_status=active`; header `Accept: application/json`; timeout 15 s; retry once on 429/5xx/connection/timeout, no backoff; keyless | MT:142-167, MT:262-264 |
| Gamma `web_fetch` fallback (agent) | same endpoint, `limit_per_type=8` | `prediction-markets/SKILL.md:20-26` |
| Filesystem append | candidate ledger (O_APPEND, 0600) | MT:353-363 |
| Plotly / kaleido | `write_html`, `write_image` (kaleido may launch a headless Chrome; failures are caught) | R:1374-1407 |
| matplotlib | Agg backend `savefig` | R:80-87, R:152-162 |
| `fcntl.flock` | manifest lock | R:1960-1972 |
| Subprocess (caller side) | bridge runs `render.py` | `deerflow_research.py:15966-15969` |
| No LLM calls in this slice | — | MT and R have no model clients (whole-file read) |

---

## Cross-module edges

**Into this slice**
- `deerflow_bridge/config.yaml:826-828` registers the tool; `config.yaml:1215-1223` whitelists tool + skills for `scoped-researcher`.
- `backend/app/services/pipeline_orchestrator.py:1358-1361`, `1533-1536` deploy MT; `pipeline_orchestrator.py:2358-2378` set env.
- `deerflow_bridge/runtime_skill_sync.py:47-52` deploys the four skills; `_is_source_noise` filters only `__pycache__`, `.DS_Store`, `.pyc/.pyo` (`runtime_skill_sync.py:98-103`).
- `deerflow_bridge/deerflow_research.py:16918-16928` (available skills), `445-477` (SKILL.md size telemetry), `518-572` (final dossier contract), `15931-16010` (render subprocess), `15361-15405` (ledger reader).
- `deerflow_bridge/linear_research.py:5548-5550` (v3 bridge calls to collector + renderer).
- Tests: `backend/tests/test_bridge_market_tools.py` (cache, single-flight, ledger, CLOB fields), `backend/tests/test_forecast_visuals_manifest.py` (manifest merge, prep_* contracts), `backend/tests/test_sessionb_skill_hygiene.py:64-67` (actor SKILL <20,000 B), `backend/tests/test_loop010_research_contracts.py:212-226` (skill wording), `backend/tests/test_deerflow_bridge_sync_guard.py:164-178` (deployment parity).

**Out of this slice**
- MT → Polymarket Gamma API (network); MT → filesystem ledger. No imports of `backend/app` or `deerflow.*` (MT:10-12; verified by imports MT:23-33, MT:145, MT:625).
- R → plotly, kaleido, matplotlib (optional). Theme mirrors `backend/app/services/report_visualizer.py:228-245` by copy, not import (R:89-99).
- Skills reference downstream artifacts/schemas (`actors.json`, `actor-role/v2`, `actors[].intelligence.dimensions`) consumed elsewhere (`actor-intelligence-contract.md:146-154`).
- Duplicate sibling: `drf2/config/market_tools.py` (248 lines, no cache/ledger) is tested by `backend/tests/test_drf2_skills_config.py:466-569`; `drf2/skills/custom/*` hold divergent skill copies.

---

## Invariants, gates, validation

- **Never raise to the agent loop**: per-query failures skipped (MT:285-290), snapshot exceptions classified (MT:491-504), impl top-level catch (MT:597-616), capture failures swallowed (MT:364-365).
- **Market eligibility**: open (`closed` not true), Yes price strictly in (0,1), `volume ≥ min_volume`, has `id`+`question` (MT:180-196).
- **Dedup and diversity**: first-seen `market_id` wins (MT:304-305); volume-desc ranking (MT:306); ≤`max_per_event` per event title (MT:231-246); ≤6 queries per call (MT:551).
- **No false absence**: transport failures and partial failures are never cached (MT:508); only `verified_empty` (all queries succeeded, zero eligible markets [verifier: more precisely, zero markets *after* `_cap_per_event`. With `PREDICTION_MARKETS_MAX=0`, eligible candidates still yield `verified_empty`/`no_equivalent_market` (MT:246, MT:473-478)]) is reported as absence and cached for ≤30 s by default (MT:476-478, MT:511-517); waiter timeouts are `inflight_timeout`, never cache hits (MT:416-446).
- **Ledger safety**: only when env root exists and the target stays inside it (MT:329-338); ≤1 MB per record (MT:350-352); serialized in-process (MT:353).
- **Renderer "never fabricate"**: skip a chart when its prep returns `None` (R:2096-2098); quant rows need source, definition, parseable as-of, comparable unit, resolvable denominator (R:807-827); trajectories need ≥3 distinct years and published-forecast provenance (R:986-1009, R:1090); revisions need ≥3 vintages with vintage year = as-of year (R:1117-1119, R:1171); markets need 0<p<1 (R:1204).
- **Manifest integrity**: only `_OWNED_CHART_IDS` rows replaced; foreign rows preserved; locked + atomic (R:1908-1983).
- **Skill gates** (prompt-level): >10pp market divergence must be explained (`prediction-markets/SKILL.md:78`); actor judge pass bar (`actor-ontology-research/SKILL.md:176-182`, enforced in code at `deerflow_research.py:14027-14045`); final dossier 10,000-word floor for deep runs (`final-dossier-contract.md:7`).

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| `requests` not installed | `_http_get` returns None → `_MarketTransportFailure` → `transport_failure` status, empty markets | MT:144-148, MT:265-266 |
| 429/5xx | retried once immediately; second failure → transport failure for that query | MT:155-165 |
| Gamma schema change (`events` missing) | per-query transport failure | MT:267-270 |
| All queries fail | `state=transport_failure`, note "no absence conclusion was reached", not cached | MT:465-469, MT:587-588 |
| Concurrent identical query | waiter shares owner result or times out after 35 s → `inflight_timeout` | MT:416-446 |
| langchain missing | tool variable `None`; impl still importable | MT:647-648 |
| Ledger dir missing/unsafe/oversized | capture silently skipped | MT:327-352 |
| plotly + matplotlib missing | render exit 3; bridge warns and skips | R:2025-2030; `deerflow_research.py:15976-15980` |
| kaleido/Chrome unavailable | matplotlib PNG; else HTML-only entry | R:1407-1415 |
| One chart throws | logged, other charts continue [verifier: true only for exceptions inside `renderer(...)`. A `prep_*` exception escapes `main()` and the script exits 1 (R:2057-2093)] | R:2099-2103 |
| No eligible artifact | stale owned rows removed from existing manifest, exit 2 | R:2120-2132 |
| Render timeout | bridge `TimeoutExpired` → warn and skip | `deerflow_research.py:15970-15975` |

---

## Surprises

1. **Default `per_query` drift (doc vs effective behavior).** MT's docstring and `DEFAULT_PER_QUERY` say 8 (MT:18-19, MT:44), and the skill fallback URL uses `limit_per_type=8` (`prediction-markets/SKILL.md:23`), but `Config.PREDICTION_MARKETS_PER_QUERY` defaults to 15 (`backend/app/config.py:1434`) and the orchestrator always exports it (`pipeline_orchestrator.py:2363`). Orchestrated runs therefore fetch 15 events per query.
2. **`PREDICTION_MARKETS_ENABLED=false` does not disable the agent tool (suspected).** MT never reads it; only the deterministic collector checks it (`deerflow_research.py:15484`) [verifier: the legacy pre-pass `_pm_initial_snapshot` gate checks it too (`deerflow_research.py:16970-16974`). The point that the agent tool ignores the flag stands]. The tool stays registered (`config.yaml:826-828`) and still calls Polymarket if an agent invokes it.
3. **The skill says an empty result is always an answer; the tool says it is not.** `prediction-markets/SKILL.md:16` says "network failure / nothing found → empty result. **An empty result is an answer**", while the tool docstring and notes say transport/in-flight states are unknown outcomes ("no absence conclusion was reached", MT:587-590, MT:640-642). `:31-33` partly reconciles this, but `:16` is still misleading.
4. **The skill overstates the cache.** "caches normalized payloads for the life of the research process" (`prediction-markets/SKILL.md:18`) holds only for non-empty successes. Empty results expire after 30 s by default, transport failures are never cached, and the LRU holds 128 entries (MT:508-525).
5. **The skill overstates ledger capture.** It says "every successful tool response is also captured" (`prediction-markets/SKILL.md:18`), but only fresh owner results with at least one market are written; `verified_empty` outcomes and cache or single-flight hits are not (MT:327-328, MT:580-581). Status-only outcomes therefore never reach the ledger, and the bridge loader ignores `status` anyway (`deerflow_research.py:15387-15403`).
6. **The single-flight wait can be shorter than the owner's worst case (suspected).** Up to 6 queries run sequentially, each with 2 attempts and a 15 s timeout. That is about 180 s or more worst case (MT:151-162, MT:280-286), while waiters give up after 35 s by default (MT:49).
7. **Possible in-flight leak on a BaseException (suspected, low likelihood).** If `snapshot_for_queries` raises a `BaseException` (not an `Exception`), `status` is unbound when `finally` evaluates `status.get(...)` (MT:450, MT:508). The resulting `UnboundLocalError` skips `flight["event"].set()` and `_QUERY_INFLIGHT.pop` (MT:526-528). Later identical queries in that process would then wait and time out.
8. **The cache key ignores query order.** The key sorts queries (MT:390), and `matched_query` is first-match-wins (MT:304-305). A permuted repeat call therefore gets the earlier call's `matched_query` labels while the `queries` field echoes the new order (MT:593).
9. **`status.candidate_count` is the pre-cap count** (MT:313, MT:464), so it can exceed `len(markets)`. With `PREDICTION_MARKETS_MAX=0`, every call returns `[]` and is labeled `verified_empty` / `no_equivalent_market` even though candidates existed (MT:246, MT:476-478).
10. **The last-resort error payload has no `queries` key** (MT:599-616), unlike the other two response shapes (MT:554, MT:593).
11. **Duplicated logic.** MT is a fork of `drf2/config/market_tools.py`, about 498 differing lines (`diff` count). Eligibility rules are re-implemented a third time in `backend/app/utils/prediction_markets.py:138` (the legacy `PolymarketClient`). [verifier: there are at least four copies. Line :138 is `_fresh_yes_price`, the requote helper. The legacy normalizer is `PolymarketClient._normalize_market` (`backend/app/utils/prediction_markets.py:503-523`), and the bridge has its own `_pm_normalize_market` (`deerflow_bridge/deerflow_research.py:14978-14997`)] The docstring says the rules match "逐条一致" (line by line) (MT:176-178), but no shared code enforces that.
12. **Quant panels with different units share one x-axis (suspected visual bug).** `render_quant` uses `make_subplots(..., shared_xaxes=True)` (R:1512-1522), yet panels can differ in unit because the key includes the unit (R:828). In plotly 6.9.0 (backend venv) this links the upper axes to the bottom one and hides their tick labels (`xaxis.matches='x3'`, `showticklabels=False`, checked in memory), so a USD/kWh panel and a % panel would share one range. The matplotlib fallback does not share axes (R:1580-1583).
13. **Timeline order is not deterministic (suspected).** `prep_timeline` sorts `set(events)` by date only (R:753). Same-date events keep set iteration order, which depends on per-process string hash randomization, so the numbered keys, and the 40-event truncation boundary when exactly tied, can vary between runs. This contradicts "deterministic, idempotent" (`forecast-visuals/SKILL.md:76`). Dates are also sorted as raw strings, so non-ISO strings such as "Late 2026" sort after ISO dates and count as "latest" (R:753-755).
14. **Escaping is inconsistent.** `_plotly_text` (the `$`→`USD` and HTML escaping helper, R:382-393) is applied to timeline and quant/trajectory hovers [verifier: only partly for trajectories. The trajectory hover's series name, period line and unit are not escaped (R:1651-1652)], but not to market bar labels (R:1790), quant y-axis labels (R:1533), subplot titles (R:1515, R:1617, R:1720), revision hover sources (R:1738) or network node names (R:1430).
15. **Doc/code threshold conflict.** `chart-patterns.md:135` says trajectories connect "once the family spans >=2 distinct years", but code requires ≥3 (R:1090), as do `forecast-visuals/SKILL.md:105` and R:1021.
16. **Small renderer doc drifts.** Comments say "six" owned producers (R:188, R:1936), but `_OWNED_CHART_IDS` lists seven (R:190-198). The module docstring says exit 0 also covers "manifest updated" (R:45), but cleanup-only runs return 2 (R:2123-2132). The manifest title "Observed and Published Forecast Trajectories" (R:2066) differs from the figure title "Observed and Sourced Forecast Trajectories" (R:1611). SKILL says the trajectory x-axis "uses `period_end`" (`forecast-visuals/SKILL.md:113`), but the plot uses the integer year, with `period_end` only in hover (R:1633, R:1652). The "no renderable artifacts" log names `sources.json`/`actors.json` (R:2129-2130) although these never render by default.
17. **Mermaid fallback contradiction.** `config.yaml:1035` says forecast-visuals has a "NO-BASH mermaid 降级路径" (no-bash Mermaid fallback path), but the skill says "Do not emit Mermaid for report delivery" (`forecast-visuals/SKILL.md:177`).
18. **Missing referenced doc.** `actor-ontology-research/SKILL.md:205` points to root `CLAUDE_ONTOLOGY.md`, which does not exist anywhere in the checkout (`find` returned nothing).
19. **Most skill prose is dormant on the default engine.** Default `RESEARCH_ENGINE=v3` (`config.py:1187`) has no slash activation (`deerflow_research.py:16689-16694`) and no `prediction_market_search` tool (`research_gateway.py:3310-3343`). The SKILL.md contracts and MT only affect legacy/`--extract-only`/evidence-lane runs, while `render.py` runs in both engines.
20. **Stray hook logs inside a skill bundle (suspected deployment leak).** `forecast-visuals/scripts/logs/…json` and `scripts/.claude/data/sessions/…json` (created 2026-09-29) are Claude Code hook dumps. They contain a session ID, a transcript path under `/Users/rogerlin/.claude/projects/…` and prompt text. Git ignores them, but `runtime_skill_sync._is_source_noise` filters only `__pycache__`/`.DS_Store`/`.pyc` (`runtime_skill_sync.py:98-103`), so they enter the source manifest and would be copied into `deer-flow/skills/public/forecast-visuals/scripts/` on the next sync, where agents can read them. The deployed copy currently lacks them (`diff -rq` shows "Only in deerflow_bridge…").
21. **Actor SKILL.md is near its size cap.** It is 19,465 bytes against the <20,000 B test cap (`backend/tests/test_sessionb_skill_hygiene.py:64-67`), leaving 535 bytes of headroom [verifier: the assert is `len(raw) < 20_000`, so the largest passing file is 19,999 B and the real headroom is 534 B (`backend/tests/test_sessionb_skill_hygiene.py:66`)].

---

## Verification

Adversarial verification was done on 2026-10-11 against the `main` checkout on disk. Repo files were read only. The only probes were in memory: a plotly 6.9.0 `make_subplots` layout check, and `prep_trajectories`/`prep_timeline` calls under three `PYTHONHASHSEED` values, run with `python -B` (no bytecode and no files written).

**Verdict counts (48 items: 15 key claims, 16 surprises, 17 spot checks):** 40 confirmed, 8 imprecise, 0 refuted, 0 unverifiable.

### Non-confirmed items and corrections

1. **Status classification (key claim; map line on the "No false absence" invariant)** — imprecise. `verified_empty` means no transport failures and zero markets *after* `_cap_per_event`, not "zero eligible markets". With `PREDICTION_MARKETS_MAX=0`, eligible candidates still produce `verified_empty`/`no_equivalent_market` (MT:246, MT:473-478).
2. **render.py exit codes (key claim, `main()` bullet)** — imprecise. Exit 3 and exit 2 are as stated, but the script exits 0 only when nothing raises. Every `prep_*` runs eagerly while the `jobs` list is built (R:2057-2093), outside the per-job try (R:2099-2103). A malformed row therefore aborts the script with exit 1. For example, `"year": NaN` raises ValueError at `int(y)` (R:937); this was reproduced in memory. Manifest lock or I/O errors also exit 1 (R:2123-2124). The bridge skips embedding on any non-zero code (`deerflow_research.py:15976-15980`).
3. **charts.json merge (key claim, Manifest bullet)** — imprecise. Only non-owned *dict* rows are kept. Non-dict items are dropped, and an unreadable or non-list charts.json counts as empty, so its foreign rows are overwritten (R:1941-1942, R:208-212). The lock is taken only when `fcntl` imports (R:63-66, R:1966-1967).
4. **`PREDICTION_MARKETS_ENABLED` (surprise 2, config table)** — imprecise. The collector is not the only consumer. The legacy pre-pass `_pm_initial_snapshot` also checks the flag (`deerflow_research.py:16970-16974`). The core point holds: MT never reads it, so the agent tool still calls Polymarket.
5. **Duplicated eligibility logic (surprise 11)** — imprecise. There are at least four copies, not three: MT:170-228, `drf2/config/market_tools.py:119`, `PolymarketClient._normalize_market` at `backend/app/utils/prediction_markets.py:503-523`, and `_pm_normalize_market` at `deerflow_bridge/deerflow_research.py:14978-14997`. The cited `prediction_markets.py:138` is `_fresh_yes_price` (requote eligibility, no volume floor), not the normalizer. The "498 differing lines" figure is confirmed.
6. **Actor SKILL.md headroom (surprise 21)** — imprecise. The test asserts `len(raw) < 20_000` (`backend/tests/test_sessionb_skill_hygiene.py:66`). At 19,465 B the file can grow by 534 B, not 535.
7. **"One chart throws → logged, other charts continue" (failure-mode table) and "per-chart try/except" (docstring bullet)** — imprecise. This holds only for exceptions raised inside `renderer(...)` (R:2099-2103). Exceptions in `prep_*` are uncaught (R:2057-2093).
8. **"`_plotly_text` is applied to ... trajectory hovers" (surprise 14)** — imprecise. Only the trajectory hover's definition, source and URL are escaped. The series name, the period line and the unit are not (R:1651-1652). The rest of surprise 14's list is correct.

### Confirmed with notes

- `_http_get` 2-attempt/no-backoff semantics (MT:151-167); `normalize_market` filters and Yes-index CLOB token (MT:180-227); ≤6 casefold-deduped queries and `no_queries` with no network (MT:539-572); cache key, no-TTL positives, 30 s negative TTL and 128 LRU (MT:389-392, MT:505-525); single-flight `inflight_timeout` (MT:416-446); ledger conditions (MT:327-363, MT:580-581); orchestrator `PER_QUERY=15` and `DEERFLOW_RUN_ARTIFACT_DIR` (`pipeline_orchestrator.py:2363`, `:2378`; `config.py:1434`).
- Default render jobs and opt-ins (R:2019-2024, R:2057-2093); `prep_quant` grouping and drops (R:789-875, panel family needs ≥2 rows, R:491); trajectories need ≥3 years vs `chart-patterns.md:135` ">=2" (R:1090). For forecast points, the internal-source regex runs over source **and** definition text (R:1007-1009).
- v3 has no slash activation and binds only `AGENT_TOOLS_SCHEMA` (web_search/web_fetch) (`deerflow_research.py:16689-16694`; `research_gateway.py:3310-3343`; `linear_research.py:183`). `linear_research.py` never references skills or `build_synthesis*`. `README.md:642` still describes "four skills" per subprocess.
- The judge pass bar matches `_JUDGE_CRITICAL` (indices 1,3,4,6,8,9,10) and `dossier_passes`. The code additionally fails an explicit `verdict == "FAIL"` and invalid scorecards (`deerflow_research.py:13902-13911`, `14027-14045`).
- Shared quant x-axes: plotly 6.9.0 sets `xaxis.matches == xaxis2.matches == 'x3'` and `showticklabels=False` (in-memory check). Timeline tie order changes across `PYTHONHASHSEED` 1/2/3 (in-memory check). The bridge sets no `PYTHONHASHSEED` (grep over `backend/app`, `deerflow_bridge`).
- Stray hook logs: four gitignored JSON files (17,332 B) with keys `session_id`, `transcript_path`, `prompt`/`prompts`, `tool_input`, `tool_response`. `_build_skill_manifest` walks hidden dirs and `logs/` (`runtime_skill_sync.py:120-146`), and `_copy_source_bundle` copies every manifest file (`runtime_skill_sync.py:274-288`). The deployed copy (dated Aug 17) lacks them.
- Spot checks that held: `_env_int("8.0")` → default (MT:84); reset wakes waiters into `inflight_timeout` (MT:368-376); `prep_network` returns None without edges and with <3 nodes (R:731); market percent rescale (R:1202); PNG clamps (R:1396-1406); timeline height and two-column key (R:1470, R:1485); `_charts_python` order (`deerflow_research.py:15863-15873`); ledger loader tags `captured_via` and ignores `status` (`deerflow_research.py:15361-15405`); the 12,000-char contract cap is injected only at `5231/6151/6175`; WAVE9 constants match `report_visualizer.py:228-245`; `prep_sources` anchor priority (R:1264-1284); revision vintage equals the as-of year (R:1118); `DRF_RUNTIME_SKILL_SYNC` verification (`deerflow_research.py:480-515`); `config.yaml:1215-1223` whitelist; permuted queries reuse the earlier `matched_query` (MT:390, MT:304-305).

### Omissions (significant behavior the map did not state)

1. **Prep exceptions are not isolated per chart.** `prep_*` results are computed eagerly while `jobs` is built (R:2057-2093). Any prep exception exits 1 before the manifest step, so stale owned rows are not cleaned up either (R:937 is a demonstrated trigger).
2. **A timed-out single-flight waiter reports `singleflight_shared: true`** (MT:435), even though nothing was shared. As a result its response is never ledgered (MT:580). Tests pin this behavior (`backend/tests/test_bridge_market_tools.py:248-250`).
3. **A corrupt or non-list charts.json loses foreign rows** on the next render (R:1941-1942). On platforms without `fcntl` the merge is unlocked (R:63-66, R:1966).
4. **A second honoring path and a fourth normalizer for markets.** The legacy pre-pass snapshot honors `PREDICTION_MARKETS_ENABLED`/`PREDICTION_MARKETS_PREPASS` (`deerflow_research.py:16970-16974`, `_pm_initial_snapshot` at `:15442`). The bridge carries its own `_pm_normalize_market` (`deerflow_research.py:14978`).
5. **The `prep_sources` docstring contradicts its code.** The docstring says "Explicit `staleness_days` wins" (R:1236), but the date-derived age wins whenever both a source date and a reference date exist. Explicit staleness is used only for undated rows (R:1299-1304). This affects diagnostics only.
6. **The per-attempt timeout is per phase.** `requests` applies `timeout=15` separately to connect and to each read (MT:153-154), so one attempt can exceed 15 s and the owner's worst case can exceed surprise 6's ~180 s estimate.
7. **The text-year fallback uses a different forecast test.** `_trajectory_year` uses `_is_projection` (R:947), not the `value_kind`-aware `_trajectory_is_forecast` (R:973-983). A row marked a forecast only via `value_kind` gets no metric-text target year and is dropped if it has no structured year.
