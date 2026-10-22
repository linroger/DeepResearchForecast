# forecast-extractor — forecast_extractor.py

Slice: `backend/app/services/forecast_extractor.py` (4201 lines, read in full on branch `main`).
All anchors are `path:line` relative to the repo root. "FE" = `backend/app/services/forecast_extractor.py`, "RA" = `backend/app/services/report_agent.py`.

## Purpose & position in the pipeline

`forecast_extractor.py` is the Stage-6 (report) library that turns research, simulation signals, prediction-market snapshots and finished report prose into the machine-readable `forecast.json` contract. It also audits that contract, and the citation discipline of the report Markdown. The module docstring (FE:1-12) says it is "dependency-light and side-effect-free (takes an LLM client, returns a dict)". In practice:

- **It writes no files.** Every artifact (`forecast.json`, `market_comparison.json`, `full_report.md`) is written by `ReportAgent` in RA.
- **It touches no network itself.** All LLM calls go through an injected client's `chat_json(messages, temperature, max_tokens)`. The one exception is `_build_ensemble_client` (FE:2593), which constructs new `LLMClient`s from env/Config.
- **It is never invoked directly by `pipeline_orchestrator.py`.** All production calls come from `ReportAgent`. Some come from offline scripts (`backend/scripts/*`) and from the `drf2` driver.

It produces the following:

1. **Scenario forecast** (mutually exclusive, sums to 1). It has two producers with one canonical shape (`_assemble_forecast`, FE:1032):
   - the pre-prose **spine**, `derive_forecast_spine` (FE:3180), called from RA:2897;
   - the post-hoc **prose extraction**, `extract_structured_forecast` (FE:999), called from RA:2972 only when no spine exists.
2. **Calibration passes on scenarios.** These are the red-team critique (`self_critique_forecast`, FE:3582), the pre-mortem (`premortem_forecast`, FE:3713), K-draw self-consistency pooling (`_pool_spine_draws`, FE:3041) and interval provenance (`apply_self_consistency_intervals`, FE:3115).
3. **Independent binary yes/no forecasts** (`extract_binary_forecasts`, FE:2652). These have:
   - a conviction/objectivity scorecard (`_binary_quality`, FE:1599);
   - Polymarket anchoring (`anchor_binaries_to_markets`, FE:1766) and the 10pp divergence revision (`enforce_market_divergence`, FE:1862);
   - an optional multi-model ensemble (FE:2801-2833);
   - source-provenance enforcement (FE:2849-2864).
4. **Contract reconciliation and audits.** These are `reconcile_forecast_contract` (FE:2435), `audit_scenario_contract` (FE:675), `audit_proposition_consistency` (FE:2270), `audit_market_anchor_integrity` (FE:2357) and `apply_horizon_consistency` (FE:2931).
5. **Deterministic Markdown renderers** for:
   - the spine prompt block (FE:3307);
   - the Part-1 binary table (FE:3353) plus an idempotent upsert (FE:3459);
   - the "How to verify" section (FE:3508).
6. **Citation tooling.** This is `audit_citation_grounding` (FE:4033) and `validate_citation_markers` (FE:4157), plus Markdown fence and table utilities (FE:3830-4030) that RA reuses heavily (RA:3518, 4107, 4268, 4348, 4445).

## Walkthrough (source order)

### Module plumbing

- **`_cfg(name, default)` (FE:25-35)** reads `getattr(Config, name, default)` behind a try/except, so it never raises.
  - Every flag is read at call time, not at import.
  - It reads **Config attributes, not env vars**. A knob that `backend/app/config.py` does not declare (for example `REPORT_PREMORTEM`) always returns the code default, whatever the environment says. See Surprises.
- **`forecast_language_rule(language)` (FE:38-63)** builds the output-language directive appended to the forecast prompts, which are written in Chinese.
  - Empty language returns `""`.
  - `zh*`, `chinese*` or a string containing "中文" returns a Chinese directive (FE:50-56).
  - Any other value returns an English `[OUTPUT LANGUAGE] Write every human-readable string value in {lang}` directive (FE:57-63).
  - JSON keys and the `low|medium|high` enums are kept verbatim.
- **`_FORECAST_INSTRUCTIONS` (FE:67-85)** is the post-hoc extraction prompt, in Chinese.
  - Schema: `headline`, `horizon`, `scenarios[name, probability, summary, key_drivers, resolution_criteria]`, `key_uncertainties`, `confidence(low|medium|high)`, `confidence_rationale`.
  - It asks for 2-5 mutually exclusive scenarios. It does **not** require a residual or status-quo bin, unlike the spine prompt.
- **`_coerce_float(v)` (FE:88-95)** calls `float(v)` and returns None on TypeError/ValueError or NaN.
  - `inf` passes through.
  - `bool` coerces, so `True` becomes 1.0.

### Scenario normalization (calibration core)

**`_normalize_scenarios(scenarios)` (FE:98-138)**

- If the input is not a list, it returns `[]`. Non-dict rows are skipped.
- Each row becomes `{name (default "未命名情景"), probability (coerced; None→0.0), summary, key_drivers[str], resolution_criteria}`.
- It keeps `base_rate_anchor` and `adjustment_rationale` only if the model supplied them (FE:116-119). **Every other field is dropped**, including `p_low`, `p_high`, `critique_note` and `self_consistency_n`.
- Probabilities are divided by their sum, when the sum is greater than 0 (FE:121-124).
- **Floor (R2-CAL-4).** `floor = _cfg("FORECAST_PROB_FLOOR", 0.0)` (FE:127). When the floor is above 0, every row below it is raised to the floor and the set is renormalized (FE:128-135).
  - The code default is 0.0, but `Config.FORECAST_PROB_FLOOR` defaults to **0.03** (backend/app/config.py:325), so the floor is active in production.
  - After renormalization a row can end slightly below the floor.
- Probabilities are rounded to 4 decimals (FE:136-137).

### Scenario-contract audit machinery

**Constants**

- `_SCENARIO_SUM_TOLERANCE = 0.015` and `_SCENARIO_VALUE_TOLERANCE = 0.015` (FE:142-143).
- `_SCENARIO_RESIDUAL_TERMS` (FE:144-149) is the list of English and Chinese residual labels: status quo, baseline, other, catch-all, 维持现状, 基准, 其它, 兜底, and so on.

**Regex sets**

- `_CRITIQUE_TARGET_PATTERNS` (FE:151-187) has five EN/ZH patterns. They extract a "revised/final/current probability … to X%" value from critique prose.
- `_EXPLICIT_TOTAL_PERCENT_PATTERNS` (FE:195-213) matches statements like "scenario probabilities sum to N%".
- `_PERCENT_ADDITION_RE` (FE:214-218) matches `a% + b% (= c%)`.
- `_ALLOCATION_CONTEXT_RE` (FE:219-223) matches scenario-allocation context words.
- The range-criterion grammars `_BETWEEN_RANGE_RE`, `_COLON_RANGE_RE`, `_CHINESE_RANGE_RE`, `_COMPARATOR_RANGE_RE` and `_CHINESE_COMPARATOR_RANGE_RE` (FE:226-268) parse `metric between X and Y unit`, `metric: X-Y`, `metric 为 X 至 Y`, `metric > X` and `metric 高于 X`.
  - Units are limited to `% K M B T thousand million billion trillion seats points units tons barrels votes`, plus a currency prefix (FE:226-233).

**Helper functions**

- **`_normalise_metric_label` (FE:271-291)** lower-cases the label and strips leading "by 2030," and articles.
  - It rejects labels shorter than 2 characters.
  - It rejects labels with no 3-letter ASCII run and no 2-character CJK run.
  - It rejects generic labels: scenario, outcome, result, metric, value.
- **`_is_residual_scenario_name` (FE:294-305)** casefolds the name.
  - Non-ASCII terms match as substrings.
  - ASCII terms must match as whole terms, with `(?<![a-z0-9])…(?![a-z0-9])`.
- **`_range_time_scope`, `_supported_range_trailing`, `_range_value` (FE:433-453)** handle the time-scope token set ("2030", "fy2030", "2030年底"), the allowed trailing text (only a time phrase) and `(number, currency+unit)` parsing.
- **`_extract_comparable_numeric_range(criteria)` (FE:456-530)**
  - It splits the text into clauses on `.`/`;`/newlines.
  - Clauses containing "or/either/或" are skipped.
  - Each clause is tried against the five grammars. A label, trailing-text or compound-`and/or` failure aborts that clause.
  - Intervals need the same unit and `low ≤ high`. Comparators map to `[x, +inf)` or `(-inf, x]`.
  - **It returns a candidate only when exactly one clause produced one** (FE:530). Otherwise it returns None (ambiguous input is skipped).
- **`_critique_probability_targets(note)` (FE:533-558)** collects target probabilities from the five patterns.
  - A match is skipped if the 32 characters before it end in base/prior/previous/initial/基准/先前/原始…, since those are historical values.
  - A value counts as a percent if it has `%` or is above 1. Only values in [0,1] are kept.
- **`_synchronize_scenario_probability_narratives(scenarios)` (FE:561-601)** works on `critique_note` and `adjustment_rationale`.
  - If any parsed target differs from the final probability by more than 0.015, the original prose is copied to `{field}_detail` (setdefault).
  - The field is then replaced with an **English** sentence: "Final calibrated probability is X% …". The text is fixed English regardless of report language.
  - It mutates the rows in place.
- **`_bad_percentage_allocations(text)` (FE:604-652)** produces three kinds of findings:
  - `stated_total`: an explicit "sum to N%" where N is not within 0.5 of 100;
  - `arithmetic_mismatch`: `a%+b%=c%` where c differs from a+b by more than 0.5;
  - `allocation_total`: an addition, inside a sentence with allocation context, whose total is not within 0.5 of 100.
- **`_json_safe_audit_value` (FE:655-668)** recursively maps non-finite floats to `"nan"`, `"infinity"` or `"-infinity"`. **`_json_safe_range_endpoint` (FE:671-672)** maps inf to None.

**`_ensure_residual_critique_scenario(scenarios, forecast)` (FE:308-412)** runs before normalization in the critique path.

- It returns `(None, False)` (critique unusable) when:
  - the input is not a list, is empty, or has a non-dict row;
  - any probability is not a JSON int/float (`type()` check, so strings and bools are rejected);
  - any probability is non-finite or outside [0,1];
  - the probabilities sum to 0 or less;
  - the sum exceeds 1.015.
- If a residual-named row already exists, it returns `(copied rows, False)`.
- Otherwise:
  - `residual_floor = min(0.20, max(0.03, FORECAST_PROB_FLOOR or 0.03))` (FE:350-351).
  - The residual is the unallocated mass `1 - sum` when that is at least `max(0.015, residual_floor)`; otherwise it is `residual_floor`, capped at 0.95 (FE:352-358).
  - The named rows are scaled to `1 - residual` (FE:359-362).
  - It appends a residual row: Chinese "其它 / 维持现状" if the headline or names contain CJK, else English "Other / Status Quo". The row has fixed summary, key_drivers and resolution_criteria (horizon-templated), plus base_rate_anchor, adjustment_rationale and critique_note (FE:364-411).
  - It returns `(rows, True)`.

**`audit_scenario_contract(forecast)` (FE:675-881)** is a fail-closed structural audit. It returns `{valid, issue_count, issues[str], examples[≤24 dicts with code/message/context]}`.

- A non-dict forecast returns invalid (FE:692-699).
- **If there is no `scenarios` key, the result is valid** (FE:700-701).
- Not a list → invalid; empty → invalid; length outside 2..5 → `scenario_count` (FE:702-712).
- Per row (FE:728-810):
  - `scenario_not_object`;
  - `scenario_name_missing`;
  - `duplicate_scenario_name` (casefold and whitespace-normalised);
  - `probability_not_numeric` (must be a finite JSON number; bool is excluded);
  - `probability_out_of_range`;
  - `resolution_criteria_missing`;
  - range parsing for overlap;
  - `stale_critique_probability`, when a critique-note target differs from the probability by more than 0.015.
- `probability_sum`: |sum−1| greater than 0.015, checked only when every probability is valid (FE:812-825).
- **`residual_scenario_missing`** when no row name is residual (FE:827-831).
- `overlapping_numeric_ranges`: a pairwise check, only for the same metric, unit and time scope. A positive-width intersection is required, so touching endpoints do not count (FE:833-856).
- `percentage_allocation_arithmetic` over the summary, resolution_criteria, critique_note, headline and confidence_rationale texts, de-duplicated (FE:858-874).

### Resolution sharpness and quality flags

- **`_RC_DATE_RE` and `_RC_METRIC_RE` (FE:888-902)** are loose date and metric lexicons.
  - Date signals: `20\d\d`, FY/CY, Q1-4, H1/H2, 年月日季, 前/底/内, by, until, before, deadline, and so on.
  - Metric signals: comparison symbols, `%`, 份额, 增速, share, rate, revenue, seats, ruling, regulation, threshold, between, and so on.
- **`validate_resolution_criteria(text)` (FE:905-921)** returns `{sharp, has_number, has_date, has_metric}`. `sharp` requires all three; `has_number` is any digit.
- **`_quality_from_scenarios(scenarios)` (FE:924-953)** adds only the keys whose flags are on:
  - `vague_criteria` when `REPORT_REQUIRE_SHARP_CRITERIA` is on (FE:931-935);
  - `missing_anchor`, plus `unjustified_anchor_jump` (|p − anchor| > 0.35 with no rationale), when `REPORT_REQUIRE_ANCHOR` is on (FE:936-952).
  - Both flags are undeclared in Config, so both are off in production and the `quality` block is not added.
- **`_anchor_to_prob(anchor)` (FE:956-969)** returns the first `N%` divided by 100, else the first `0.xx` fraction, clamped to [0,1].
- **`slice_head_tail(text, budget, head_ratio=0.6)` (FE:972-996)**
  - If the budget is not an int, is 0 or less, or the text fits, it returns the text unchanged.
  - Otherwise the head ratio is clamped to [0.05, 0.95] and the result is `head + "\n…(中段略)…\n" + tail`.

### Post-hoc scenario extraction

**`extract_structured_forecast(report_markdown, llm, situation_brief=None, language="")` (FE:999-1029)**

- It slices the report head+tail using `FORECAST_EXTRACT_BUDGET` (40000) and `FORECAST_EXTRACT_HEAD_RATIO` (0.6).
- The prompt is `_FORECAST_INSTRUCTIONS` + `[态势简报]` (brief[:2000]) + `[预测报告]` + the language rule.
- One `chat_json` call with temperature 0.2 and `FORECAST_EXTRACT_MAX_TOKENS` (4096).
- A non-dict reply becomes `{}`. The result passes through `_assemble_forecast`.
- **It does not catch `chat_json` exceptions**; the docstring says the caller wraps it.

**`_assemble_forecast(raw)` (FE:1032-1056)** produces the canonical dict:

- `{headline, horizon, scenarios (normalized), key_uncertainties[str], confidence (low|medium|high, default/invalid → "medium"), confidence_rationale, schema_version: 1}`;
- plus `quality`, only when `_quality_from_scenarios` is non-empty.

### Binary-forecast prompts and constants

- **`_BINARY_FORECAST_INSTRUCTIONS` (FE:1066-1096)** is an English `str.format` template. It asks for:
  - `{"binary_forecasts":[…]}` rows with id, statement (one sentence with the number and date inside), probability 0.02-0.98 (independent, not summing to 1), resolution_criteria (metric + number + date + source), resolution_source, theme, horizon_year, base_rate_anchor, adjustment_rationale and source (the simulation signal name or "research-prior");
  - plus `proposition_id` and `scenario_membership{derivable, yes_scenarios}`;
  - at least `{min_count}` distinct forecasts, with no clustering in 0.40-0.60.
- `_BINARY_DEFAULT_THEME_ENUM` and `_BINARY_DEFAULT_TIE_RULE` (FE:1099-1100) are used when no themes are given (RPT-6).
- `_BINARY_CONTRARIAN_RULE` (FE:1104-1109) asks for about 40-50% of forecasts with p < 0.5. `_BINARY_LOW_P_RULE` (FE:1112-1116) restricts top-up forecasts to p in 0.05-0.35.
- `_BINARY_MARKET_RULE` (FE:1122-1131) asks the model to cite Polymarket implied probabilities, explain divergences above 10pp, and add an optional `market_anchor{market_id, implied_yes_prob}`.

### Source-provenance enforcement (anti-fabricated provenance)

- **`_SIM_SIGNAL_TAXONOMY` (FE:1142-1165)** has seven entries `(canonical name, block-marker regex for the signal pack, label regex for free-text source)`:
  - world-state outcome shares, matched by `【预测结果分布\s*P\(outcome\)`;
  - salience tiers, `议程设置力分层`;
  - coalition map, `##\s*派系/联盟图`;
  - causal spine, `【因果骨架`;
  - scenario diff, `##\s*情景对比\s*/\s*反事实差异`;
  - projected edges, `【关系演化投影`;
  - simulation outcomes, `##\s*模拟量化结果`.

  The comment at FE:1140-1141 says this table must be kept in sync with the renderer headers. See Surprises: the world-state header has drifted.
- `_SOURCE_ALWAYS_ALLOWED_RE` (FE:1169-1170) always allows research-prior, scenario-partition, 研究先验 and 情景划分. `_SOURCE_MARKET_LABEL = "prediction markets"` and `_SOURCE_MARKET_RE` (FE:1172-1174) cover market labels.
- **`allowed_signal_labels(signal_pack)` (FE:1177-1185)** returns the canonical names whose marker occurs in the exact prompt slice.
- **`_enforce_source_provenance(binaries, allowed)` (FE:1188-1213)**
  - It skips binaries with an empty or always-allowed source.
  - Otherwise it maps the source to a canonical name (the market label first, then the first matching taxonomy label).
  - If the canonical name is unknown or not in `allowed`, it sets `source_claimed = original` and `source = "research-prior"`.
  - It returns the number of downgrades. It mutates in place.

### World-state outcome → explicit sim prior (SIM-ADD-3)

- **`world_state_outcome_from_signal_pack(signal_pack)` (FE:1230-1272)**
  - It finds the `_WS_OUTCOME_HEADER_RE` header (FE:1223).
  - It then scans the following lines for `· name: NN%` share lines (FE:1224-1225), stopping at any line that starts with one of `_WS_OUTCOME_SECTION_BREAK` (FE:1227).
  - Shares are normalized to a sum of 1.
  - `converged` is False if the remaining text contains "尚未趋稳", True if it contains "趋稳", else None.
  - It returns `{scenario_shares (4dp), converged, source: "world-state outcome shares"}`, or None.
  - No `converged_at` key is ever produced.
- **`_norm_scenario_key(name)` (FE:1275-1277)** is a loose name key. It is byte-identical to `ensemble._norm_name` (backend/app/services/ensemble.py:27-29).
- **`_record_sim_adjustment(forecast, world_state_outcome)` (FE:1280-1322)**
  - It returns None, and writes nothing, when the shares are missing or empty.
  - Otherwise it computes `delta_vs_research_prior[name] = share − scenario.probability` for scenarios whose names match.
  - It writes `forecast["sim_adjustment"] = {scenario_shares, converged, converged_at, delta_vs_research_prior, source}`.

### Binary normalization and circular-market filter

- **`_binary_key(stmt)` (FE:1325-1326)** lower-cases the statement and collapses non-word runs to spaces. It is the dedup key, and is also imported by `ensemble.pool_binary_forecasts` (backend/app/services/ensemble.py:281).
- **Market circularity regexes (FE:1329-1378)** cover EN/ZH market entities, quote nouns, quote-movement verbs, settlement verbs, current-time words, model-subject blockers, ZH deadlines and ZH quote levels.
- **`_has_market_scoped_movement` (FE:1381-1398)** returns true when a movement verb follows a quote noun within 120 characters with no "model/forecast" subject switch in between.
- **`_market_forecast_clause_is_circular(clause)` (FE:1401-1443)**
  - EN: with a settlement verb it returns circular unless the clause is current and has no movement. Otherwise it needs a quote noun and a scoped movement.
  - ZH: similar, plus an implicit future level. A deadline that precedes the market entity together with "概率为X%" counts as circular, unless a current-time word is present.
- **`_is_circular_market_forecast(statement, criteria)` (FE:1446-1454)** splits on sentence punctuation and returns True if any clause of the statement or the criteria is circular. Such binaries are **dropped** (FE:1479-1481). They predict a market price, not the real event.

**`_normalize_binaries(items, *, start_index=1, allowed_themes=None, market_lookup=None)` (FE:1457-1596)**

- It drops non-dicts, an empty statement, a non-numeric probability, circular-market forecasts and duplicate `_binary_key` values (FE:1474-1485).
- The probability is clamped to **[0.02, 0.98]** and rounded to **2 dp**, independently, with no sum normalization (FE:1486, 1502).
- `horizon_year` is `int(float(x))` or None (FE:1488-1492).
- `theme` is lower-cased. When `allowed_themes` is given, an unknown theme becomes the last allowed theme; otherwise an empty theme becomes "general" (FE:1493-1498).
- Row fields:
  - `id` (model id or `F{start_index+len(out)}`);
  - `statement`, `probability`, `resolution_criteria`, `resolution_source`, `theme`, `horizon_year`, `base_rate_anchor`, `adjustment_rationale`;
  - `source` (default "research-prior");
  - `proposition_id`: kebab-cased model value, else `"forecast-" + sha256(key)[:12]` (FE:1510-1516);
  - `criteria_sharp`: `validate_resolution_criteria(statement + " " + criteria).sharp` (FE:1520-1521).
- `scenario_membership` validation (FE:1523-1582):
  - `derivable` must be a JSON bool, otherwise it becomes None and an error is recorded.
  - `yes_scenarios` must be a list of non-empty, unique strings.
  - With `derivable=false` and names present, the names move to `discarded_yes_scenarios` and the list is emptied.
  - Errors go to `validation_errors`.
  - A non-dict membership becomes `{derivable: None, yes_scenarios: [], validation_errors: ["…must be an object"]}`. It is kept so that it fails closed.
- `market_anchor` (FE:1583-1594): if the model gave a dict, the snapshot price from `market_lookup[market_id]` overrides the model's number. A valid result is stored minimally as `{market_id, implied_yes_prob (4dp), divergence = p − ip}`.

### Binary quality scorecard (publish-gate input)

**`_binary_quality(binaries, *, min_count, themes_expected=None)` (FE:1599-1651)**

- Statistics: `n`; mean; **population** stdev; `midband` (count with 0.40 ≤ p ≤ 0.60); `conviction` (count with p ≥ 0.70 or p ≤ 0.30); `sharp` (count of stored `criteria_sharp`); a theme histogram seeded with zeros for the expected themes; `theme_cardinality`.
- `passed = n ≥ min_count AND std ≥ 0.12 AND midband_share ≤ 0.40 AND conviction ≥ 3 AND sharp ≥ int(0.8·n)` (FE:1626-1632).
- `issues` lists every failed criterion, plus a single-theme warning when n > 1 and cardinality ≤ 1. The theme warning does not affect `passed` (FE:1633-1645).
- Returns `{count, prob_stdev, midband_share, conviction_count, sharp_criteria_count, themes, theme_cardinality, passed, issues}`.

### Prediction-market anchoring (PM-2) and influence boundary (LOOP-017)

- **`_MARKET_MATCH_INSTRUCTIONS` (FE:1661-1673)** is the batch matching prompt. It returns `{"matches":[{forecast_id, market_id|null, resolution_equivalence exact|near|loose, confidence}]}`.
- **`_MARKET_DIVERGENCE_INSTRUCTIONS` (FE:1678-1688)** is the revision prompt. It returns `{"revisions":[{id, probability, adjustment_rationale}]}`.
- `_MARKET_EQUIVALENCE_RANK` = exact 3 / near 2 / loose 1 (FE:1690). `_MARKET_MENTION_RE` = `market|polymarket|市场|預測|预测市场|implied` (FE:1692).
- **`_market_end_date` (FE:1695-1697)** returns `end_date` or `endDate`.
- **`_rationale_cites_market(text, anchor)` (FE:1700-1711)** is true on a keyword hit, or when the text contains the anchor's implied probability as an integer percent.
- **`_build_market_anchor(prob, market, *, equivalence, match_confidence, binary)` (FE:1714-1763)**
  - It returns None when the market id is missing or the implied probability is invalid.
  - Anchor fields: `{market_id, question, implied_yes_prob, price_at_research (= implied), divergence (= prob − implied; prob None → 0.0)}`, plus `url`, `endDate`, `resolution_equivalence` and `match_confidence` (clamped to [0,1], 3dp) when present.
  - With a binary, it adds the byte-binding fields `forecast_proposition_id`, `forecast_contract_sha256` (sha256 of `statement\ncriteria`), `market_question_sha256` and `match_method="bounded-semantic-equivalence-review"`.
- **`anchor_binaries_to_markets(binaries, markets, llm, *, language="English", max_markets=24)` (FE:1766-1831)**
  - It is gated by `FORECAST_MARKET_ANCHORING` (default true).
  - It keeps valid markets, truncated to 24, and builds the forecast lines (statement[:220]) and market lines (question[:200], implied %, end date).
  - One `chat_json` call with temperature 0.1 and max_tokens 1500. **Exceptions are caught** and give 0 anchors (FE:1801-1806).
  - Matches are accepted only when the forecast id and market id resolve and the equivalence rank is at least `FORECAST_MARKET_ANCHOR_MIN_EQUIVALENCE` (default "near", so loose matches are dropped).
  - An accepted match **overwrites** `b["market_anchor"]` with the rich anchor.
  - Returns the anchor count.
- **`_stamp_market_influence(binary, anchor, *, prior_p, revised_p)` (FE:1834-1859)** writes a durable `market_influence` record: `{market_id, market_question, price_at_revision, prior_probability, revised_probability, match_confidence, resolution_equivalence}`. When the same market is revised again, the original `prior_probability` is preserved.
- **`enforce_market_divergence(binaries, llm, *, language)` (FE:1862-1945)**
  - It is gated by `FORECAST_MARKET_DIVERGENCE_REVISION` (default true).
  - Candidates need an anchor, |divergence| > 0.10, a rationale that does not already cite the market, and **match_confidence ≥ `FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE` (0.6; missing confidence excludes the candidate)**.
  - One `chat_json` call with temperature 0.2 and max_tokens 2048. Exceptions are caught and give 0.
  - A revision is accepted only if its new rationale cites the market (FE:1928-1930).
  - The new probability is clamped to [0.02, 0.98] at 2dp and the divergence is recomputed.
  - If the probability actually changed, the influence stamp is written (FE:1942-1943).
  - Returns the count of accepted revisions.
- **`build_market_comparison(binaries)` (FE:1948-2013)** is pure.
  - Each anchored binary gives a comparison row: `{forecast_id, statement, model_probability, market_id, market_question, market_implied_yes_prob, price_at_research, divergence (recomputed from the canonical probabilities, not the cached value; FE:1967-1970), abs_divergence, exceeds_10pp, resolution_equivalence, match_confidence, url, endDate, rationale_cites_market}`.
  - `influences[]` and `influence_count` are added only when some binary has a `market_influence` record.

### Cross-artifact proposition contract

- **`_proposition_key_text(value)` (FE:2017-2066)** is a hard-coded US-Congress event classifier. It returns one of `d_sweep`, `d_house_r_senate`, `r_effective_senate`, `d_house_net_seat_change`, `r_house_net_seat_change`, `d_house`, `r_house`, or "".
- **`_binary_proposition_key` (FE:2069-2075)** returns "" when the statement key and criteria key are both non-empty and disagree.
- **`_binary_proposition_conflict` (FE:2078-2087)** describes that mismatch.
- **`_market_proposition_key(question)` (FE:2090-2106)** is the market-side classifier.
- **`_scenario_yes_membership(binary, scenarios)` (FE:2109-2267)** returns `(key, yes_names, expected_prob, error)`.
  - A proposition conflict returns `"conflicting-binary-contract"`.
  - With a membership dict:
    - every malformation returns `"invalid-scenario-membership"`;
    - a valid `derivable=false` with empty names returns `("", [], None, None)`, so there is no reconciliation;
    - `derivable=true` requires at least one name, all present in the partition with valid probabilities, and no duplicate partition names.
    - It returns `(proposition_id or "explicit-scenario-membership", names, round(sum,4), None)`.
  - **Without a membership** it falls back to the heuristic: the US-Congress key is matched against the scenario names using "d house", "r senate", "50/50", "r trifecta" substrings (FE:2227-2267).
- **`audit_proposition_consistency(forecast)` (FE:2270-2319)** is read-only.
  - Invalid or conflicting memberships are always mismatches.
  - A derivable binary is a mismatch when |binary − scenario-sum| > 0.015.
  - Returns `{checked, rows, mismatches, mismatch_count, passed}`.
- **`_market_anchor_complete(anchor)` (FE:2322-2332)** requires non-empty market_id, question, url, endDate and resolution_equivalence; an implied probability in [0,1]; **match_confidence ≥ 0.5**; and equivalence exact or near.
- **`_market_anchor_binding_valid(binary, anchor)` (FE:2335-2354)** requires the proposition id to equal the anchor's `forecast_proposition_id`, `match_method` to be bounded-semantic, and both sha256 values to match the current bytes.
- **`audit_market_anchor_integrity(forecast)` (FE:2357-2387)** adds issue reasons for:
  - incomplete provenance;
  - a classified key mismatch;
  - an unclassified anchor whose byte-binding is invalid.
- **`_restore_market_influence(binary, removed_market_id, restored)` (FE:2390-2432)**
  - It only runs when the stamp's market id equals the removed anchor's id.
  - It always sets `anchor_removed=True`.
  - Partition-governed binaries (`membership.method == "mutually-exclusive-scenario-partition"`) are never rolled back.
  - It rolls the probability back to `prior` only when the current probability equals the stamp's `revised` and differs from `prior`. It then appends an English note to the rationale and records the id.

**`reconcile_forecast_contract(forecast, world_state_outcome=None)` (FE:2435-2589)** mutates the forecast and returns diagnostics.

1. `before` = proposition audit (FE:2458).
2. **Partition override (FE:2460-2491).** For each binary with a derivable key, `scenario_membership` is set to `{derivable: True, proposition_key, yes_scenarios, implied_probability, method: "mutually-exclusive-scenario-partition"}`. If |actual − expected| > 0.015, then:
   - `pre_reconciliation_probability` is recorded;
   - **probability = expected** (4dp);
   - `source = "scenario-partition"`;
   - an English note is appended to the rationale.
3. **Richest anchor per market_id (FE:2495-2509).** The anchor with the most non-empty fields wins.
4. **Remove or merge anchors (FE:2511-2533).** The richest anchor is merged with the binary's own non-empty fields. The anchor is popped when the proposition does not match (classified keys differ and the byte-binding is invalid) or the merged anchor is incomplete. Popping triggers `_restore_market_influence`.
5. **Transfer (FE:2535-2553).** A complete, classified richest anchor is attached to the single binary with the same proposition key. `price_at_research` is backfilled.
6. Divergences are recomputed (FE:2555-2562). `forecast["binary_forecasts"]` is set to the dict rows, and `forecast["market_comparison"] = build_market_comparison(...)`. **This is always written, even when `comparisons` is empty** (FE:2564-2565).
7. `after` audit, market audit, diagnostics `{corrected, corrected_count, removed_market_anchors, restored_market_influences, transferred_market_anchors, before, after, market_anchors, passed}` (FE:2566-2579).
8. `sim_adjustment` comes from the explicit argument or from `forecast["binary_quality"]["world_state_outcome"]` (FE:2581-2587).
9. `forecast["proposition_consistency"] = diagnostics` (FE:2588).

### Multi-model ensemble (ITEM 12)

- **`_build_ensemble_client(provider)` (FE:2593-2617)**
  - It looks up `Config.PROVIDER_META[p]`.
  - CLI providers, and unknown names, go to `LLMClient(provider=p)`. An unknown name raises ValueError inside LLMClient.
  - OpenAI-compatible providers get their key from env `{P}_API_KEY`, then env `meta.key_env`, then `Config.LLM_API_KEY` only if p equals the primary `LLM_PROVIDER`. They get `default_base` and `default_model`.
- **`_run_ensemble_draws(models, draw_fn, min_count, *, primary_provider, client_factory, skipped)` (FE:2620-2649)**
  - It de-duplicates names and skips the primary.
  - Each model gets one draw: `draw_fn(min_count, [], client=client)`. There is no top-up and no low-p pass.
  - A failure or an empty result appends the model to `skipped`.
  - Returns `{model: binaries}`.

### `extract_binary_forecasts(...)` (FE:2652-2894) — main binary entry point

**Inputs:** `report_markdown` (RA passes the research dossier, `self.research_report`, falling back to the report), `llm`, `min_count=10`, `language="English"`, `situation_brief`, `themes`, `signal_pack`, `market_pack`, `markets`, `scenarios`, `ensemble_client_factory`, `horizon_date`.

**Setup (FE:2679-2716)**

1. The input is sliced head+tail with `FORECAST_BINARY_EXTRACT_BUDGET` (48000) and the head ratio.
2. Themes are lower-cased; an empty list becomes None.
3. `contrarian` = `FORECAST_BINARY_CONTRARIAN` (true).
4. **`sim_sensitive`** requires `SIMULATION_FORECAST_EFFECT == "legacy_prompt"` AND `FORECAST_SIM_SENSITIVITY` AND a non-empty signal pack (FE:2688-2692). Under the default `diagnostic_only`, the simulation signals **never enter the binary prompt**.
5. `market_aware` = `PREDICTION_MARKETS_ENABLED` AND a non-empty `market_pack`.
6. `market_lookup` maps market_id to implied probability, from `markets`.
7. Horizon-year hint: `horizon_date` is parsed with `utils.dates.parse_as_of`. Its year is used, otherwise the hint is `"2027"` with the rule "within 1-5 years of now" (FE:2706-2716).

**Inner `_draw(instr_min, exclude, *, low_p=False, client=None)` (FE:2718-2772)** builds the prompt from:

- the formatted instructions;
- the contrarian or low-p rule;
- the SIMULATION SENSITIVITY rule (when `sim_sensitive`);
- `_BINARY_MARKET_RULE` (when `market_aware`);
- up to 30 exclusions;
- `[Situation brief]` (brief[:2000]);
- `[Simulation quantitative signals]` (pack[:4000]);
- `[Prediction market signals]` (pack[:8000]);
- `[Canonical mutually-exclusive scenario partition]` (str(rows)[:6000]), with derivable instructions;
- `[Research dossier]`.

It makes one `chat_json` call with temperature 0.25 and max_tokens 4096, then calls `_normalize_binaries`. `_merge` (FE:2774-2780) de-duplicates by `_binary_key`.

**Sequence**

1. First draw with `min_count` (FE:2782).
2. If short, **one** top-up with `need+2`, excluding statements already captured (FE:2783-2785).
3. If contrarian and (stdev < 0.12 or min p > 0.5), one low-p draw of `max(3, min_count//3)` in a try/except (FE:2788-2797).
4. **Renumber ids F1..Fn** (FE:2799-2800).
5. Ensemble, when `FORECAST_ENSEMBLE_MODELS` is non-empty: secondary draws → `ensemble.pool_binary_forecasts(..., extremize_a=ENSEMBLE_EXTREMIZE_A, spread_threshold=FORECAST_ENSEMBLE_SPREAD_THRESHOLD)`. This sets `binary["ensemble"]` and overwrites the probability. It is wrapped in try/except (FE:2806-2833).
6. If `markets` were passed: `anchor_binaries_to_markets` → `enforce_market_divergence` → `build_market_comparison`, all in try/except (FE:2836-2844).
7. Provenance enforcement. The allowed set comes from `signal_pack[:4000]` only if `sim_sensitive`, plus "prediction markets" when `market_aware` (FE:2849-2852).
8. Output `{binary_forecasts, binary_quality}`. `binary_quality` gets:
   - `provenance_downgrades`, plus an issue line when it is above 0;
   - `world_state_outcome`, only when that label is allowed (FE:2869-2872);
   - the `ensemble` block `{enabled_models, pooled_models, skipped, low_agreement, spread_threshold}` plus an issue line;
   - and `out["market_comparison"]` only when there are comparisons (FE:2853-2894).

### Requirement-horizon consistency (RQ-6)

- **`_plausible_years` (FE:2908-2915)** and **`parse_requirement_years(text, now_year)` (FE:2918-2928)** return years matching `\b20\d\d\b` inside [now−1, now+30].
- **`apply_horizon_consistency(forecast, requirement_text, *, now_year, horizon_date)` (FE:2931-2998)**
  - It is gated by `FORECAST_HORIZON_CHECK` (true).
  - Requirement years come from the requirement text, plus the `horizon_date` year (from `parse_as_of`), or else from `sim_timeline.extract_horizon(text, date(now_year,1,1))`.
  - Binary years come from `horizon_year` plus the years in the statement and criteria.
  - When both sets are non-empty and **disjoint**, it merges `quality["horizon_mismatch"] = {requirement_years, binary_years, detail}`.
  - Any exception is logged and the forecast is returned unchanged.

### Forecast spine (P0-1)

- **`_SPINE_INSTRUCTIONS` (FE:3002-3026)** is the Chinese spine prompt. It requires 2-5 MECE scenarios **including a 维持现状/其它 residual**, anchor-and-adjust fields, and objective resolution criteria.
- **`_spine_draw` (FE:3029-3038)** makes one `chat_json` call and passes the result through `_assemble_forecast`.
- **`_pool_spine_draws(draws, floor)` (FE:3041-3109)**
  - The first draw fixes the scenario set. The probability is the mean across draws, matched by `ensemble._norm_name`.
  - `p_low` and `p_high` are mean ± the **sample** stdev, and `self_consistency_n` is recorded.
  - Means are renormalized, then floored and renormalized again, and rounded. The bounds are widened to contain p.
  - It writes `self_consistency_k` and `self_consistency_mean_spread`.
  - Confidence is demoted high→medium at spread ≥ 0.15 and medium→low at spread ≥ 0.25.
- **`SELF_CONSISTENCY_INTERVAL_SOURCE` (FE:3112) and `apply_self_consistency_intervals(forecast)` (FE:3115-3177)**
  - No-op unless `self_consistency_k ≥ 2` and the spread is finite and at least 0.
  - Valid existing bounds are kept; pooled bounds (n ≥ 2) are tagged `interval_source`.
  - Missing or invalid bounds become `clamp(p ± spread)`, tagged.
  - It writes `interval_provenance{source, k, spread}`.
- **`derive_forecast_spine(llm, *, central_question, horizon, situation_brief, forecast_inputs, signal_pack, base_distribution, quantitative_facts, market_block, language)` (FE:3180-3304)**
  - Input caps: brief 2000, inputs 6000, signal 6000, facts 3000 (FE:3208-3211); question[:600]; horizon[:120]; market block[:6000] with the 10pp rule (FE:3226-3231).
  - Quantitative-facts block (FE:3233-3235).
  - WorldState base-distribution block, used only when `REPORT_SPINE_ANCHOR_WORLDSTATE` is set and `base_distribution` is a dict (FE:3237-3244).
  - Language rule.
  - `max_tokens = REPORT_SPINE_MAX_TOKENS` (6144). `floor = FORECAST_PROB_FLOOR`. `k = REPORT_SPINE_SELFCONSISTENCY_K` (Config default 1).
  - First draw at temperature 0.2. **If it returns no scenarios, one retry** (FE:3256-3260).
  - When k > 1, the follow-up draws keep the scenario names and use temperature `min(0.9, 0.2+0.15i)`. Draws with no scenarios are dropped.
  - Pooling, then `derived_from="spine"`.
  - The R2-CAL-18 divergence pass computes `worldstate_divergence` per scenario. At ≥ 0.2 it widens the interval by d/2 each side. Thin-evidence divergences go into `quality.model_vs_sim_divergence`, and confidence is demoted from high (FE:3277-3302).
  - Finally `apply_self_consistency_intervals`.

### Renderers

- **`render_forecast_spine_block(forecast, max_scenarios=6)` (FE:3307-3345)** is a Chinese-only, deterministic prompt block. It contains the headline/horizon, up to 6 lines of `· [NN%] name — 判定：criteria[:160]`, the confidence and an "align, don't silently diverge" instruction. It returns "" when there are no scenarios.
- **`_esc_cell` (FE:3348-3350)** replaces `|` with `／` and newlines with spaces.
- **`render_binary_forecasts_block(forecast, language="English")` (FE:3353-3456)** renders the deterministic Part-1 table.
  - Headers are Chinese unless `language.lower()` starts with "en".
  - Columns: `#`, statement, `NN%` (with ±spread and ⚠ when the per-binary ensemble spread exceeds the threshold), full resolution criteria (not truncated; WAVE9), theme.
  - A market P(yes) column with `(Δ±Npt)` is added if any anchor exists.
  - Footer: count / conviction / sharp, plus an ensemble low-agreement footnote from `binary_quality.ensemble`.
- **`upsert_binary_forecasts_block(markdown, block)` (FE:3459-3505)** takes one of three paths:
  1. Owned markers `<!-- binary-forecast-block:start/end -->` exist → replace between them. Returns noop if the bytes are unchanged, else "replaced".
  2. A legacy H2 "Part 1 — Binary Forecasts" or "第一部分·二元预测" exists → replace up to the next `## ` heading ("replaced").
  3. Otherwise insert after the H1 title, or at the top ("inserted").

  An empty block returns noop.
- **`render_resolution_block(forecast, indicators, language="Chinese")` (FE:3508-3569)** renders the "How to verify / 如何验证本预测" section: per-scenario `[pct] name: criteria` (with a placeholder when criteria are missing), plus an indicators table of up to 20 rows (indicator, date_or_trigger, discriminates). The default language is Chinese.

### Red-team critique and pre-mortem

- **`_CRITIQUE_INSTRUCTIONS` (FE:3572-3579)** is the Chinese red-team prompt. It asks for the same structure plus a `critique_note` per scenario. It does not ask the model to echo `base_rate_anchor` or `adjustment_rationale`.
- **`self_critique_forecast(forecast, llm, language="")` (FE:3582-3647)**
  - One `chat_json` call with temperature 0.2 and **max_tokens 2048**.
  - If the reply has no scenario list, the original is returned.
  - `_ensure_residual_critique_scenario` runs; a None result returns the original.
  - Then: `_normalize_scenarios` → copy `critique_note` → adopt the critic's `confidence` and `confidence_rationale` (the headline and horizon are kept from the original) → `_enforce_humility_monotone` → `_synchronize_scenario_probability_narratives`.
  - If a residual was added: `residual_scenario_added=True`, the original rationale goes to `confidence_rationale_detail`, and the rationale is replaced with fixed **English** text (FE:3628-3639).
  - **If `audit_scenario_contract(out)` is not valid, the original forecast is returned** (FE:3640-3641).
  - Otherwise `critiqued=True` and `apply_self_consistency_intervals`.
  - Any exception returns the original.
- **`_close_probability_rounding(scenarios)` (FE:3650-3675)** rounds to 4dp and puts the rounding residue on the residual-named row, or else the last row, if the result stays in [0,1].
- **`_enforce_humility_monotone(orig, new)` (FE:3678-3703)** caps the new peak at the original peak and redistributes the excess proportionally to the other rows, then closes the rounding.
- **`_PREMORTEM_INSTRUCTIONS` (FE:3706-3710)** asks for `{underweighted_scenario, missed_signals, overconfident_scenario}`.
- **`premortem_forecast(forecast, llm, language="")` (FE:3713-3773)**
  - It is gated by `REPORT_PREMORTEM` (code default False; not declared in Config, so effectively always off).
  - When it runs, it makes one `chat_json` call with temperature 0.3 and max_tokens 1024.
  - Missed signals are appended to `key_uncertainties`, capped at 12.
  - It moves `min(0.05, 0.25·p_over)` from the overconfident to the underweighted scenario.
  - It then synchronizes narratives, writes the `premortem` block, invalidates bounds that no longer contain p, and calls `apply_self_consistency_intervals`. Any exception returns the original.

### Citation audit and Markdown utilities

- **Regexes**
  - `_CITATION_RE` = `[\[【]\s*S\d+\s*[\]】]` (FE:3780). It does not accept the tier suffix `S1-a`.
  - `_NUMBER_RE` = `\d+(\.\d+)?\s*%|\b\d{2,}(\.\d+)?\b|\b\d{4}年` (FE:3781). Years count as quantitative claims.
  - `_SIM_GROUNDING_RE` (FE:3784-3788) matches agent quotes `> "`, causal edges `--[…]-->`, and `[SIM`, `[sim_id`, `[E\d`, `[EDGE`, `【模拟`, `【图谱`.
- **Markers:** `BINARY_FORECAST_START_MARKER` and `BINARY_FORECAST_END_MARKER` (FE:3791-3792), and `_AUTHORED_FORECAST_H2_RE` (FE:3794-3804) for the four authored H2 titles.
- **`markdown_fence_transition(line, state)` (FE:3830-3850)** is a CommonMark fence state machine. A fence closes only on the same character, a length at least the opening length, and no info string.
- **`markdown_table_cells` (FE:3853-3864)** handles optional outer pipes and escaped `\|`, and requires at least 2 cells. **`is_markdown_table_delimiter` (FE:3867-3872)** and **`is_markdown_table_header` (FE:3875-3881)** use it.
- **`split_markdown_claim_units(text, *, table_header, table_delimiter)` (FE:3884-3936)**
  - Header and delimiter rows return `[]`.
  - Table cells are independent surfaces. Prose has its list prefix stripped and is split on `_QUANT_CLAIM_BOUNDARY_RE` (FE:3808-3817).
  - Dotted initialisms are merged back.
  - A leading `[S#]` fragment is re-attached to the previous unit.
- **`format_markdown_table_row` (FE:3939-3951)**, **`markdown_table_cell_index` (FE:3954-3966)** and **`markdown_table_claim_context` (FE:3969-3998)** handle table row rebuild, offset→cell mapping, and the semantic context: row label + header numbers + claim.
- **`authored_forecast_markers_balanced(lines)` (FE:4001-4019)** checks that start/end markers are ordered and paired outside fences. **`is_authored_forecast_heading` (FE:4022-4030)** matches the authored H2 titles.
- **`audit_citation_grounding(report_markdown, index_map=None, *, exclude_authored_forecasts=False)` (FE:4033-4141)**
  - It walks the lines. Fence lines and fenced content are skipped (fenced numeric lines are counted in `ignored_fenced_quantitative_lines`). Headings are skipped.
  - When `exclude_authored_forecasts` is set, authored blocks (only when the markers are balanced) and authored H2 sections are excluded and counted.
  - Claim units with a `_NUMBER_RE` hit are kept.
  - Outputs:
    - `quantitative_claims`;
    - `cited` / `coverage` (source **or** sim/edge grounding);
    - `source_cited` / `source_coverage` (`_CITATION_RE` only);
    - `unsupported_samples` (8 × [:200]);
    - with `index_map`: `resolved_cited` / `resolved_coverage` (the tag must resolve in the index);
    - optional exclusion and fence counters.
  - With no claims, coverage is 1.0.
- **`_CITATION_TAG_RE` (FE:4145)** accepts `S\d+(-[A-Za-z])?`. **`_norm_citation_tag` (FE:4148-4154)** strips brackets and whitespace, upper-cases S and lower-cases the suffix.
- **`validate_citation_markers(report_markdown, index_map=None)` (FE:4157-4201)** is fence-aware.
  - Returns `{total_markers, distinct_tags, order (first appearance), counts, dangling (not in index), uncited (index tags never used, sorted by (len, tag))}`.
  - `dangling` and `uncited` are empty when `index_map` is None.

## Control flow

**Production path.** `ReportAgent.generate_report` drives everything in this order.

1. **Spine before prose.** When `REPORT_STRUCTURED_FORECAST` and `REPORT_FORECAST_SPINE_FIRST` are set (RA:11243-11245), `_derive_and_pin_forecast_spine` runs (RA:2847).
   - Under `diagnostic_only`, `signal_pack=""` (RA:2869-2879). The market pack is built if missing. The horizon comes from `as_of_date`, overridden by the calendar `horizon_date` (RA:2888-2895).
   - It calls `_fe.derive_forecast_spine` (RA:2897-2906, FE:3180). **It never passes `base_distribution` or `quantitative_facts`.**
   - If `REPORT_CRITIQUE_BEFORE_PROSE` and `REPORT_FORECAST_SELF_CRITIQUE` are set (both default true; backend/app/config.py:174 and 633), it runs `self_critique_forecast` (FE:3582) → `premortem_forecast` (FE:3713, effectively a no-op) (RA:2916-2931).
   - `render_forecast_spine_block` (FE:3307) is pinned into the section prompts (RA:2934), and the spine is written early as `forecast.json` (RA:2936-2939).
2. **Report sections are written.** RA reuses `render_forecast_spine_block` at RA:8790.
3. **`_finalize_structured_forecast`** (RA:2951; called at RA:11502).
   - It uses the spine if present, else `extract_structured_forecast` (FE:999) (RA:2969-2976).
   - It critiques if not already critiqued (RA:2980-2985).
   - It calls `audit_citation_grounding(report, index_map=_citation_index)` (RA:2999-3000).
   - When `FORECAST_EMIT_BINARY` is set (backend/app/config.py:317), it calls `extract_binary_forecasts(research_report or report, …, scenarios=forecast.scenarios, markets, market_pack, signal_pack, horizon_date)` (RA:3095-3106). Then:
     - `forecast[binary_*]` is set from the result (RA:3108-3109);
     - `reconcile_forecast_contract(forecast)` (FE:2435) (RA:3110);
     - `_binary_quality` is **recomputed and replaces `binary_quality`** (RA:3111-3117);
     - `apply_horizon_consistency` (FE:2931) (RA:3124-3126);
     - `market_comparison.json` is written from `forecast["market_comparison"]`, which reconcile set (RA:3132-3142).
   - Repair passes reuse `audit_citation_grounding` (RA:3229).
   - `forecast.json` is written (RA:3195).
4. **Part-1 table.** `_prepend_binary_forecasts_section` calls `render_binary_forecasts_block` + `upsert_binary_forecasts_block` (RA:8643-8665, called from RA:11510).
5. **Resolution section.** `_append_resolution_section` calls `render_resolution_block` (RA:4807-4816; called from RA:11534).
6. **Citation finalization.** Fence and table utilities and `validate_citation_markers` / `_norm_citation_tag` are used at RA:3257, 3346, 3518, 4107, 4268, 4348, 4445, 4540, 6113, 6281, 6413, 7862 and 8185.
7. **Final read-only audit** (RA:8455-8577). It calls `audit_citation_grounding(exclude_authored_forecasts=True)`, `validate_citation_markers`, `audit_proposition_consistency`, `audit_market_anchor_integrity` and `audit_scenario_contract`. These feed `_final_audit_integrity_issues` (RA:8280, 8376-8400) and then the publish gate (RA:9151).

**Inside `extract_binary_forecasts`** (FE:2782-2894): draw → (top-up) → (low-p) → renumber → (ensemble) → (market anchor → divergence revision → comparison) → provenance → scorecard → world-state outcome → ensemble block.

## Data & artifacts

The module **reads and writes no files** (FE:10-11). The artifacts below are produced by RA from this module's return values.

**`forecast.json`** (written by RA:2939 for the early spine and RA:3195 for the final version, under `ReportManager._get_report_folder(report_id)`).

- Top-level keys produced here:
  - `headline`, `horizon`, `scenarios[]`, `key_uncertainties[]`, `confidence`, `confidence_rationale`, `schema_version: 1` (FE:1043-1051);
  - optional `quality{vague_criteria, missing_anchor, unjustified_anchor_jump, model_vs_sim_divergence, horizon_mismatch}`;
  - `derived_from: "spine"` (FE:3274);
  - `self_consistency_k` and `self_consistency_mean_spread` (FE:3101-3102);
  - `base_distribution` (FE:3280);
  - `critiqued`, `residual_scenario_added`, `confidence_rationale_detail` (FE:3629-3642);
  - `premortem{underweighted_scenario, missed_signals}` (FE:3759);
  - `interval_provenance{source, k, spread}` (FE:3172);
  - `binary_forecasts[]`, `binary_quality{…}`, `market_comparison{anchored_count, comparisons[], influences?, influence_count?}`, `proposition_consistency{…}`, `sim_adjustment{…}` (FE:2564-2588).
- Scenario row: `name`, `probability` (4dp), `summary`, `key_drivers[]`, `resolution_criteria`, plus optional `base_rate_anchor`, `adjustment_rationale`, `critique_note`, `critique_note_detail`, `adjustment_rationale_detail`, `p_low`, `p_high`, `self_consistency_n`, `interval_source`, `worldstate_divergence`.
- Binary row: `id` (F1..Fn), `statement`, `probability` (2dp, or 4dp after partition reconcile), `resolution_criteria`, `resolution_source`, `theme`, `horizon_year`, `base_rate_anchor`, `adjustment_rationale`, `source`, `source_claimed?`, `proposition_id`, `criteria_sharp`, `scenario_membership{derivable, yes_scenarios, discarded_yes_scenarios?, validation_errors?, proposition_key?, implied_probability?, method?}`, `pre_reconciliation_probability?`, `market_anchor{market_id, question, implied_yes_prob, price_at_research, divergence, url?, endDate?, resolution_equivalence?, match_confidence?, forecast_proposition_id?, forecast_contract_sha256?, market_question_sha256?, match_method?}`, `market_influence{…, anchor_removed?, probability_restored?}`, `ensemble{models, probs, pooled, spread}`.

**`market_comparison.json`** (RA:3132-3142) has the same shape as `build_market_comparison` (FE:2009-2013).

**`full_report.md`** is not written here. The Part-1 block is bounded by `<!-- binary-forecast-block:start/end -->` (FE:3472-3474, 3791-3792).

**In-memory inputs.** `signal_pack` is the signal-block text that RA renders. `market_pack` is the rendered Polymarket table. `markets` is the normalized snapshot list `{market_id, question, implied_yes_prob, url?, end_date?}` (backend/app/utils/prediction_markets.py:526-540). `index_map` maps citation tags to sources.

## Config / env knobs

All knobs are read through `_cfg` (Config attributes). "Config default" refers to `backend/app/config.py`.

| Knob | Code default → Config default | Effect | Anchor |
|---|---|---|---|
| `FORECAST_PROB_FLOOR` | 0.0 → **0.03** (config.py:325) | Per-scenario floor and renormalize; residual floor in critique | FE:127, 350, 3249 |
| `FORECAST_EXTRACT_BUDGET` | 40000 (config.py:738) | Character budget for post-hoc scenario extraction | FE:1012 |
| `FORECAST_EXTRACT_HEAD_RATIO` | 0.6 (config.py:740) | Head share of the head+tail slice (also for binaries) | FE:1013, 2681 |
| `FORECAST_EXTRACT_MAX_TOKENS` | 4096 (config.py:742) | Max tokens for post-hoc extraction | FE:1025 |
| `REPORT_REQUIRE_SHARP_CRITERIA` | False (not in Config) | Adds `quality.vague_criteria` | FE:931 |
| `REPORT_REQUIRE_ANCHOR` | False (not in Config) | Adds `quality.missing_anchor` / `unjustified_anchor_jump` | FE:936 |
| `FORECAST_MARKET_ANCHORING` | True (config.py:721) | PM-2 batch matching | FE:1773 |
| `FORECAST_MARKET_ANCHOR_MIN_EQUIVALENCE` | "near" (config.py:724) | Minimum match strictness | FE:1788-1789 |
| `FORECAST_MARKET_DIVERGENCE_REVISION` | True (config.py:727) | 10pp revision pass | FE:1874 |
| `FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE` | 0.6 (config.py:733) | Minimum match confidence for a market to move a probability | FE:1876-1893 |
| `FORECAST_BINARY_EXTRACT_BUDGET` | 48000 (config.py:739) | Binary dossier slice | FE:2680 |
| `FORECAST_BINARY_CONTRARIAN` | True (config.py:634) | Contrarian rule and low-p top-up | FE:2684, 2728, 2788 |
| `SIMULATION_FORECAST_EFFECT` | "diagnostic_only" (config.py:1492-1497) | Only `legacy_prompt` lets sim signals into the binary prompt | FE:2688-2692 |
| `FORECAST_SIM_SENSITIVITY` | True (config.py:635) | Also required for sim injection | FE:2691 |
| `PREDICTION_MARKETS_ENABLED` | True (config.py:1423) | Injects the market table and allows the market source label | FE:2693 |
| `FORECAST_ENSEMBLE_MODELS` | "" (config.py:643) | Comma list of secondary providers; empty disables | FE:2809 |
| `ENSEMBLE_EXTREMIZE_A` | None → 1.0 (config.py:333) | Log-odds pooling factor | FE:2821 |
| `FORECAST_ENSEMBLE_SPREAD_THRESHOLD` | 0.15 (config.py:646) | Low-agreement threshold | FE:2826, 2883 |
| `FORECAST_HORIZON_CHECK` | True (config.py:637) | RQ-6 flag | FE:2948 |
| `REPORT_SPINE_INPUT_CAP_{BRIEF,INPUTS,SIGNAL,FACTS}` | 2000/6000/6000/3000 (not in Config) | Spine input truncation | FE:3208-3211 |
| `REPORT_SPINE_ANCHOR_WORLDSTATE` | False → **true** (config.py:344) | WorldState prior in the spine; inert because no caller passes `base_distribution` | FE:3237 |
| `REPORT_SPINE_MAX_TOKENS` | 6144 (not in Config) | Spine max tokens | FE:3248 |
| `REPORT_SPINE_SELFCONSISTENCY_K` | 1 → 1 (config.py:329) | K spine draws | FE:3251 |
| `REPORT_PREMORTEM` | False (not in Config) | Pre-mortem pass | FE:3719 |
| env `{PROVIDER}_API_KEY`, `meta.key_env`, `Config.LLM_API_KEY` | — | API keys for ensemble clients | FE:2612-2614 |

Knobs read by the caller that gate this module: `REPORT_STRUCTURED_FORECAST`, `REPORT_FORECAST_SPINE_FIRST`, `REPORT_FORECAST_SELF_CRITIQUE`, `REPORT_CRITIQUE_BEFORE_PROSE`, `FORECAST_EMIT_BINARY`, `FORECAST_BINARY_THEMES`, `BINARY_FORECASTS_MIN_COUNT` (RA:11243, 2916, 2980, 3042, 3053, 8724).

## External calls

- **LLM** (all through the injected client's `chat_json`; `LLMClient.chat_json` retries once at temperature −0.2 and then raises `ValueError`, backend/app/utils/llm_client.py:597-627):

  | Call | Temperature | max_tokens | Anchor |
  |---|---|---|---|
  | Post-hoc extraction | 0.2 | 4096 | FE:1022 |
  | Market matching | 0.1 | 1500 | FE:1802 |
  | Divergence revision | 0.2 | 2048 | FE:1909 |
  | Binary draw (primary, top-up, low-p, ensemble) | 0.25 | 4096 | FE:2768 |
  | Spine draw | 0.2 (follow-ups up to 0.9) | 6144 | FE:3031, 3256, 3268 |
  | Critique | 0.2 | 2048 | FE:3592 |
  | Pre-mortem | 0.3 | 1024 | FE:3726 |

- **New LLM clients:** `LLMClient(provider=…, api_key, base_url, model)` (FE:2606-2617). These can reach any OpenAI-compatible endpoint in `Config.PROVIDER_META` (backend/app/config.py:858-877), or the CLI providers.
- **No HTTP, subprocess or DB access in this module.** Polymarket data arrives pre-fetched in `markets` and `market_pack`.
- **Local imports:**
  - `..config.Config` (FE:32, 2605);
  - `..utils.llm_client.LLMClient` (FE:2606);
  - `..utils.dates.parse_as_of` (FE:2709, 2958);
  - `..utils.sim_timeline.extract_horizon` (FE:2963);
  - `.ensemble.pool_binary_forecasts` (FE:2820) and `.ensemble._norm_name` (FE:3049, 3278, 3738).

## Cross-module edges

**Callers into this slice**

- `backend/app/services/report_agent.py`, the only production caller.
  - Spine: RA:2855-2934.
  - Finalize: RA:2966-3117 (extract, critique, citation audit, binary extraction, reconcile, `_binary_quality`, horizon check).
  - Repair: RA:3229.
  - Citation and Markdown utilities: RA:3257, 3346, 3518-3546, 4107, 4268, 4348, 4445, 4540, 6113, 6281, 6413, 7862, 8185.
  - Resolution block: RA:4811.
  - Final audit: RA:8455-8539.
  - Part-1: RA:8654.
  - Spine block reuse: RA:8790.
- `backend/app/services/ensemble.py:281` imports `_binary_key`.
- Scripts:
  - `backend/scripts/backfill_report_visuals.py:26-33`: `_binary_quality`, `_is_circular_market_forecast`, `build_market_comparison`, `reconcile_forecast_contract`, `render_binary_forecasts_block`, `upsert_binary_forecasts_block`;
  - `backend/scripts/model_comparison.py:53-57`: extract, critique, citation audit;
  - `backend/scripts/eval_forecast_quality.py:156`: `audit_citation_grounding`.
- `drf2/driver/gates.py:32` imports `_binary_quality`.
- Tests: `backend/tests/test_forecast_extractor.py` (62 tests) and about 16 other test modules (`grep -rl forecast_extractor backend/tests`).

**Outgoing:** see External calls. `ensemble.pool_binary_forecasts` mutates `binary["probability"]` and `binary["ensemble"]` (backend/app/services/ensemble.py:261-345).

**Downstream consumers of fields this module emits:**

- `interval_provenance` and `self_consistency_mean_spread`: backend/app/services/report_visualizer.py.
- `market_influence`: frontend/src/utils/binaryForecasts.js and frontend/src/components/research/BinaryForecastTable.vue.
- `criteria_sharp` and per-binary `ensemble`: backend/app/services/exec_brief.py:461.
- `binary_quality.passed` and `issues`: the publish gate (RA:9206-9211).

## Invariants, gates, validation

- **Scenarios are mutually exclusive and sum to 1.**
  - `_normalize_scenarios` normalizes, floors and rounds (FE:121-137).
  - `audit_scenario_contract` requires 2-5 rows, unique names, finite probabilities in [0,1], a sum within 1±0.015, a residual bin, non-empty criteria, no positive-width overlap of numeric ranges, no stale critique numbers and no bad percentage arithmetic (FE:675-881).
  - In the final audit, a non-valid contract is a hard issue when `REPORT_STRUCTURED_FORECAST` is set (RA:8390-8400).
- **Binaries are independent.** Each is clamped to [0.02, 0.98] with no sum normalization (FE:1486). They are de-duplicated by normalized statement (FE:1482-1485). Market-quote forecasts are dropped (FE:1479-1481).
- **Binary publish gate.** `_binary_quality.passed` is defined at FE:1626-1632. A failure demotes confidence through the publish gate as an epistemic issue (RA:9206-9211).
- **Partition consistency.** A binary fully determined by the scenarios must equal the sum of its YES scenarios within 0.015. `reconcile_forecast_contract` forces this (FE:2474-2478). The final audit treats a remaining mismatch as a hard issue (RA:8376-8382).
- **Market anchors.**
  - The implied probability always comes from our snapshot, never the model's transcription (FE:1587-1588, 1722-1731).
  - The divergence is always recomputed (FE:1939, 1970, 2562).
  - A durable anchor requires a complete record (conf ≥ 0.5, exact/near, url, endDate) and a proposition match or byte-binding (FE:2322-2354). Otherwise it is stripped in reconcile (FE:2526-2528). A remaining integrity issue is a hard issue in the final audit (RA:8383-8389).
- **Market influence boundary.** Only anchors with conf ≥ 0.6 may move a probability. A revised rationale must cite the market (FE:1891-1893, 1928-1930). A move leaves a stamp that is never removed. If the anchor is later stripped, the probability is restored unless the partition now governs it (FE:2390-2432).
- **Provenance.** A simulation-signal source must reconcile to a block marker in the injected prompt slice, or it is downgraded (FE:1188-1213, 2849-2852).
- **Humility monotone.** The critique cannot raise the peak scenario probability (FE:3678-3703).
- **Simulation containment (Foglamp WP1).**
  - Simulation signals reach the binary prompt only under `legacy_prompt` (FE:2688-2692).
  - The spine gets `signal_pack=""` from RA under `diagnostic_only` (RA:2869-2879).
- **Citation coverage.** The grounded ratio uses source or sim markers; the strict ratio uses sources only; the resolved ratio requires tags in the index (FE:4112-4135). Authored forecast sections are excluded only when the markers are balanced (FE:4060, 4071-4074).

## Failure modes & recovery

- **LLM exceptions.** `chat_json` raises `ValueError` after two unparseable replies. What happens next depends on the call:
  - Propagated to the caller: `extract_structured_forecast` (FE:1022), `derive_forecast_spine` (FE:3256, 3269; the K>1 follow-ups are unprotected) and the first and top-up binary draws (FE:2782, 2785).
  - RA catches and logs. The spine falls back to post-hoc extraction (RA:2946-2949). Binaries are lost entirely (RA:3155-3156).
- **Swallowed failures (degrade-safe).** The low-p draw (FE:2792-2797), each ensemble model (FE:2646-2648), the whole ensemble (FE:2832-2833), market matching (FE:1801-1806), divergence revision (FE:1908-1913), the anchoring block (FE:2842-2844), critique (any exception, or an invalid contract, returns the input; FE:3640-3641, 3646-3647), pre-mortem (FE:3772-3773) and horizon check (FE:2996-2998).
- **Malformed JSON shape.** A non-dict becomes `{}` (FE:1027-1028, 3036-3037). A missing list gives `[]` or 0 anchors.
- **Empty spine.** It is retried once (FE:3257-3260). RA then skips the spine and uses post-hoc extraction (RA:2907-2909).
- **Critique rejection paths.** The critique returns the original forecast unchanged (FE:3600-3613, 3640-3641) when:
  - any probability is not a JSON number or lies outside [0,1], including percent-scale values like `35`;
  - the sum exceeds 1.015;
  - non-dict rows are present;
  - the post-residual contract is invalid.
- **Wrong anchors.** They are removed in reconcile, and the influence is rolled back (FE:2526-2531).

## Surprises

1. **Confirmed drift: the world-state header no longer matches.**
   - `_SIM_SIGNAL_TAXONOMY` and `_WS_OUTCOME_HEADER_RE` match `【预测结果分布 P(outcome)` (FE:1144, 1223). The live renderer now emits `【推演结果分布 P(outcome)（elicited model projection…` (RA:2494).
   - So even under `legacy_prompt`, the "world-state outcome shares" label is never allowed: such sources are always downgraded, `world_state_outcome` is never set, and `sim_adjustment` is never recorded.
   - The tests still use the old header (backend/tests/test_sessionb_sim_additivity.py, test_sessionb_forecast_provenance.py, test_audit_fixes_report.py). One test uses the new header but only checks prompt inclusion (backend/tests/test_foglamp_containment.py:323).
   - The comment at FE:1140-1141 explicitly requires keeping the table in sync.
2. **Confirmed (cross-module): RA throws away part of the binary result.** RA replaces `forecast["binary_quality"]` with a freshly recomputed `_binary_quality` (RA:3111-3117). This drops `provenance_downgrades`, the provenance issue line, `world_state_outcome` and the `ensemble` block that `extract_binary_forecasts` built (FE:2858-2891). As a result, the ensemble low-agreement footnote and the configured `spread_threshold` in `render_binary_forecasts_block` (FE:3396-3400, 3445-3455) never fire in production. The per-binary ±spread still renders with the 0.15 fallback.
3. **Undeclared knobs.** `REPORT_PREMORTEM`, `REPORT_REQUIRE_SHARP_CRITERIA`, `REPORT_REQUIRE_ANCHOR`, `REPORT_SPINE_MAX_TOKENS` and `REPORT_SPINE_INPUT_CAP_*` are not declared in `backend/app/config.py`, and `_cfg` reads Config attributes, not env vars. Setting them as environment variables has no effect, so the pre-mortem is effectively dead code. DRF_ARCHITECTURE.md:1684 lists `REPORT_PREMORTEM` as a knob.
4. **Dead inputs: R2-CAL-3/16/18 are inert in production.** `derive_forecast_spine`'s `base_distribution` and `quantitative_facts` are never passed by any caller (the only call is RA:2897-2906). The `REPORT_SPINE_ANCHOR_WORLDSTATE=true` default (config.py:344) therefore changes nothing. With `REPORT_SPINE_SELFCONSISTENCY_K=1` (config.py:329), `_pool_spine_draws` and `apply_self_consistency_intervals` are also no-ops in default runs.
5. **Doc drift.**
   - FE:125-126 says the floor defaults to 0.0 and is "byte-identical to the old path". The Config default is 0.03 (config.py:325), and ARCHITECTURE_MAP.md:567 also says 0.0.
   - DRF_ARCHITECTURE.md:1189 and 1684 say K defaults to 5; the code says 1.
   - DRF_ARCHITECTURE.md §10.3 line anchors (`_assemble_forecast:851`, `derive_forecast_spine:2514`, `_normalize_scenarios:69-108`, and so on) are stale. The actual lines are 1032, 3180 and 98-138.
   - DRF_ARCHITECTURE.md:1182-1184 describes the spine as consuming simulation signals and S-tier facts. Under `diagnostic_only` it gets neither.
6. **`horizon_mismatch` has no consumer.** It is said to be "for the publish gate to demote confidence" (FE:2902-2903, 2938-2939; RA:3120). No code in backend/app, drf2, scripts or frontend reads it.
7. **`FORECAST_BINARY_REQUIRE_SHARP` is dead.** It is declared at config.py:320 with the comment "regenerate non-sharp items once", but nothing in backend/app reads it, and no per-item regeneration exists in this module.
8. **Suspected: binary loss on a top-up failure.** An exception in the top-up draw (FE:2785) discards the successful first-pass binaries, because only the low-p draw is wrapped (FE:2792). This contradicts the docstring's "degrade-safe" claim (FE:2664-2666).
9. **Suspected: critique silently discarded.** If the critic returns 5 named scenarios without a residual, `_ensure_residual_critique_scenario` appends a 6th. That breaks the 2-5 count rule in `audit_scenario_contract`, so the whole critique is discarded silently (FE:3606-3641, 707-712). Percent-scale critic probabilities (e.g. 35) are also rejected outright (FE:339-340).
10. **Suspected: anchor-and-adjust fields may be lost.** `_CRITIQUE_INSTRUCTIONS` (FE:3577-3578) does not ask the model to echo `base_rate_anchor` or `adjustment_rationale`, and `_normalize_scenarios` keeps them only if echoed (FE:116-119). The critique runs by default before prose, so the spine's anchor-and-adjust audit trail can vanish from `forecast.json`. The critique's max_tokens of 2048 (FE:3598) is also below the 4096/6144 budgets raised elsewhere to avoid truncated 5-scenario JSON.
11. **Suspected: English text is hard-coded.**
    - The stale-number rewrites (FE:591-601), the residual-added `confidence_rationale` (FE:3634-3639), and the reconcile and influence notes (FE:2479-2482, 2424-2428) are fixed English even for Chinese reports.
    - Conversely, `render_binary_forecasts_block` and `render_resolution_block` choose Chinese for any language not starting with "en" (FE:3366, 3525). A French report, for example, gets Chinese headers.
    - `render_forecast_spine_block` is Chinese-only (FE:3318-3344).
12. **Suspected: the citation audit misses Chinese numbers.** Because `\b` is Unicode-aware in `_NUMBER_RE` (FE:3781), numbers glued to CJK characters do not count as quantitative claims. Probing the regex shows `"收入达到120亿美元"` → no match and `"在2030年前"` → no match. Separately, bare years (e.g. "2030") do count as claims needing a citation.
13. **Citation regexes disagree.** `_CITATION_RE` (FE:3780) rejects tiered tags such as `[S1-a]`, but `_CITATION_TAG_RE` (FE:4145) accepts them. A `[S1-a]`-only unit therefore counts toward `resolved_coverage` but not toward `coverage` or `source_coverage`.
14. **Suspected: loose heuristics.**
    - `_RC_DATE_RE` matches `H[12]` inside "H100" and any "内"/"前" character (FE:888-892). Probe: "Nvidia H100 shipments exceed 5 million units" counts as having a date, so `criteria_sharp` may over-report.
    - `_MARKET_MENTION_RE` matches the bare substring "market" (FE:1692). A rationale mentioning "market share" counts as citing the market, which exempts the binary from the 10pp revision (FE:1889-1890) and inflates `rationale_cites_market`.
    - The salience label regex matches "tier" inside words such as "frontier" (FE:1148).
15. **Duplicated logic.**
    - `_norm_scenario_key` (FE:1275-1277) is identical to `ensemble._norm_name` (backend/app/services/ensemble.py:27-29).
    - The publish gate keeps its own substring-based residual-label list (RA:9185-9190). It cites a nonexistent "`_RESIDUAL_LABELS` / line ~119" in the extractor; the real constant is `_SCENARIO_RESIDUAL_TERMS` (FE:144) and uses term matching. The two lists differ: the gate lacks catch-all, remainder and otherwise, and has "status" as a bare substring.
    - The 2dp clamping convention is duplicated between `_normalize_binaries` (FE:1486) and `pool_binary_forecasts`, which rounds without clamping (backend/app/services/ensemble.py:340).
16. **Suspected: ensemble may pool unrelated forecasts.** Secondary ensemble draws are not renumbered. `pool_binary_forecasts` falls back to matching by `id` when the statement keys differ (backend/app/services/ensemble.py:322-326), so a secondary "F3" about a different event can be pooled into the primary F3.
17. **Model-volunteered minimal anchors are always stripped in reconcile.** The minimal anchors `{market_id, implied_yes_prob, divergence}` from `_normalize_binaries` (FE:1589-1594) lack url, endDate and match_confidence, so they fail `_market_anchor_complete` and are removed in reconcile (FE:2526-2528). The only exception is when another binary's rich anchor for the same market fills those fields and the proposition classifies as US-Congress. The proposition classifier is hard-coded to US House/Senate control (FE:2017-2106); other domains rely only on byte-binding.
18. **`market_comparison` is always written.** `reconcile_forecast_contract` writes `forecast["market_comparison"]` even when there are no anchors (`{"anchored_count": 0, "comparisons": []}`; FE:2565). Meanwhile `extract_binary_forecasts` omits the key in that case (FE:2892-2893), and RA ignores `_bres["market_comparison"]` entirely (RA:3107-3110).
19. **Pre-mortem docstring drift.** The docstring says "then renormalize" (FE:3716, 3747), but the code only transfers mass, which preserves the sum, and never calls `_close_probability_rounding`. It is inert by default anyway (Surprise 3).
20. **`audit_scenario_contract` passes a forecast with no `scenarios` key** (FE:700-701). The publish path relies on RA's `structured.get("required")` branch to catch missing forecasts.
