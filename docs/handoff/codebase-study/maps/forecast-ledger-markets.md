# forecast-ledger-markets — Forecast ledger, ensemble, backtest, resolution autorun, requirement spec, research progress, prediction markets util

Scope (branch `main`, checkout on disk, read 2026-10-11). Every line of these seven files was read:

| File | Lines |
|---|---|
| `backend/app/services/forecast_ledger.py` | 436 |
| `backend/app/services/ensemble.py` | 419 |
| `backend/app/services/backtest.py` | 237 |
| `backend/app/services/resolution_autorun.py` | 117 |
| `backend/app/services/requirement_spec.py` | 105 |
| `backend/app/services/research_progress.py` | 564 |
| `backend/app/utils/prediction_markets.py` | 884 |

Anchors are `path:line`, relative to the repo root. "Suspected" marks a finding inferred from reading the code. None of these findings was checked by running anything.

---

## Purpose & position in the pipeline

This slice holds the support code around the forecasting stages. Each module is small, mostly pure, and degrade-safe:

- **Calibration loop.** `forecast_ledger.py` (JSONL ledgers), `backtest.py` (Brier, log-loss, calibration and recalibration maths) and `ensemble.py` (multi-seed and multi-model pooling) sit after the REPORT stage. `ReportAgent._finalize_structured_forecast` appends each finished `forecast.json` to the ledger and reads historical calibration back (`backend/app/services/report_agent.py:3181-3204`). The orchestrator's seed-ensemble step pools the forecasts from several seeds (`backend/app/services/pipeline_orchestrator.py:8717-8718`). `forecast_extractor` pools binary forecasts from several models (`backend/app/services/forecast_extractor.py:2820-2832`).
- **Resolution autorun.** `resolution_autorun.py` is an in-process scheduler. It runs the external `backend/scripts/resolution_monitor.py` as a subprocess. That script re-quotes anchored Polymarket markets, detects resolutions, and appends to `resolutions.jsonl` through `forecast_ledger.append_market_resolution`.
- **Requirement spec.** `requirement_spec.py` parses the user's brief (`prediction_requirement.txt`, called `simulation_requirement` in ReportAgent) into a small contract: output language, minimum binary-forecast count, page budget, themes. ReportAgent uses it in five places.
- **Research progress.** `research_progress.py` turns the DeerFlow bridge's streamed `research_progress.log` lines into a monotonic, phase-banded percentage (RESEARCH stage, `pipeline_orchestrator.py:2477-2496`). It also serves bounded or full multi-track log snapshots to `GET /api/research/<id>/progress` (`backend/app/api/research.py:871-921`).
- **Prediction markets.** `utils/prediction_markets.py` is a keyless client for the **Polymarket only** Gamma and CLOB APIs, with query derivation, LLM relevance scoring and a markdown renderer. The REPORT stage uses it for a fallback live fetch, to re-quote the research-time snapshot and to render the market pack (`report_agent.py:2570-2778`). The resolution monitor uses it for re-quotes and resolution lookups. The research-stage market fetch does **not** use this module; it uses mirrored copies in `deerflow_bridge/` (see Surprises).

---

## Walkthrough (source order)

### 1. `backend/app/services/forecast_ledger.py`

Module docstring (`:1-13`): this is the NEXTSTEPS P2-4 calibration ledger. It says resolution happens through `/api/v1/resolve` or the `forecast_tools backtest` CLI, and mentions an "atomic rewrite for resolution". **Neither exists in code** (see Surprises). Imports are stdlib only: `json, os, threading` (`:15-20`).

- **`ledger_dir()`** (`:23-31`): returns `Config.FORECAST_LEDGER_DIR` when non-empty. Otherwise it returns `os.path.join(Config.PIPELINE_DATA_DIR, "_forecast_ledger")`. If importing `Config` raises, it falls back to the relative `uploads/pipelines/_forecast_ledger`, which resolves against the CWD. The default `PIPELINE_DATA_DIR` is `backend/app/../uploads/pipelines` (`backend/app/config.py:1581`). No side effects.
- **`_ledger_file(d=None)`** (`:34-35`): returns `<d or ledger_dir()>/ledger.jsonl`.
- **`evaluation_ledger_dir()`** (`:38-46`): returns `dirname(ledger_dir().rstrip(sep))/_evaluation_ledger`, a **sibling** of the production ledger dir. With the default config that is `.../uploads/pipelines/_evaluation_ledger`. If the dirname is empty it uses `./_evaluation_ledger`.
- **`is_production_calibration_row(e)`** (`:49-63`): returns False for non-dicts, for rows with truthy `golden` or `characterization_only`, and for rows whose `record_class` is `"evaluation"` (case and whitespace insensitive). Returns True otherwise. This is the read-side filter for Foglamp WP1 1E/I-21.
- **`append_forecast(forecast, *, report_id, horizon=None, resolution_date=None, created_at=None, d=None, objective_signals=None)`** (`:66-110`):
  - Returns None when `forecast` is not a dict, or when it has no dict scenarios (`:80-88`).
  - Keeps only `{name, probability, resolution_criteria}` for each scenario (`:82-86`).
  - Horizon is the argument, else `forecast["horizon"]` stripped, else None (`:89`).
  - Entry fields (`:90-100`): `report_id`, `horizon`, `resolution_date` (argument or `_year_end(hz)`), `created_at`, `scenarios`, `confidence`, `resolved: False`, `outcome: None`, `schema_version: 1`.
  - Adds `objective_signals` only when it is a non-empty dict (`:101-102`).
  - Side effect: `os.makedirs` on the parent, then appends one JSON line (`ensure_ascii=False`) in `"a"` mode (`:103-108`). **There is no lock and no deduplication.**
  - Returns the entry, or None on `OSError` (`:109-110`).
- **`append_golden_result(*, question_id, probability, resolved_outcome, question, category, resolution_date, as_of_date, resolution_criteria, report_id, d, objective_signals)`** (`:113-185`):
  - Coerces `probability` to float. Returns None on TypeError/ValueError and on NaN or ±inf (`:133-138`). Clamps to [0,1] (`:139`).
  - Returns None when `question_id` is empty after stripping (`:140-142`).
  - `outcome` is `"YES"` if `resolved_outcome` is truthy, else `"NO"` (`:143`).
  - Builds two scenarios, YES = round(p,4) and NO = round(1−p,4) (`:144-147`).
  - Entry (`:148-168`): `resolved: True`, `outcome`, `golden: True`, `question_id`, `category`, `question`, `as_of_date`, `record_class: "evaluation"`, `characterization_only: True`. `report_id` defaults to `golden:<qid>`.
  - **Redirect** (`:175-178`): if `abspath(d or ledger_dir()) == abspath(ledger_dir())`, the target becomes `evaluation_ledger_dir()` and the entry gets `ledger_redirected: "evaluation"`. Paths are compared with `abspath`, not `realpath`, so a symlinked alias of the production dir would not be redirected. The read-side filter is the second defence.
  - Appends one line to `<target>/ledger.jsonl` (`:179-183`). Returns the entry, or None on `OSError`.
- **`_year_end(horizon)`** (`:188-209`): turns a horizon string into a resolution date.
  - Returns None for empty input.
  - Collects the `20xx` years found by `sim_timeline._TIER4` (`backend/app/utils/sim_timeline.py:245`), a private regex.
  - Sets `as_of = date(min(years)-1, 1, 1)`, or today when the text has no year.
  - Calls `sim_timeline.extract_horizon(text, as_of)` (`sim_timeline.py:266`). That function tries explicit date, then anchored period, then relative offset, then bare year; the bare-year tier picks the **largest** year, mapped to 12-31.
  - Returns `res.horizon_date` (ISO) or None. Any exception gives None.
- **`read_ledger(d=None)`** (`:212-230`): reads `ledger.jsonl` line by line. Skips blank and unparseable lines, which tolerates a torn tail. Returns `[]` if the file is missing or on `OSError`.
- **`calibration_summary(d=None, entries=None, *, include_evaluation=False)`** (`:233-261`):
  - Takes rows with truthy `resolved`, `outcome` and `scenarios`, plus `is_production_calibration_row` unless `include_evaluation` is set (`:246-251`).
  - Maps each to `{"forecast": {"scenarios"}, "outcome"}`.
  - Returns `{n_resolved: 0, mean_brier: None, calibration_error: None}` when nothing qualifies.
  - Otherwise calls `backtest.calibration_report` (lazy import, default 5 bins) and returns `{n_resolved, mean_brier, calibration_error}`. On exception it returns Nones with the count.
- **`due_for_resolution(as_of, d=None)`** (`:264-274`): returns unresolved rows whose `resolution_date` is ≤ `as_of`. The comparison is a lexicographic string compare. It does **not** apply the production-row filter.
- **`recalibration_param(d=None, entries=None, *, include_evaluation=False)`** (`:277-311`):
  - Uses the same resolved and production filter as above (`:291-296`).
  - `enabled = bool(Config.REPORT_RECALIBRATE_FROM_LEDGER)`, defaulting to False. **That attribute is not defined in `config.py`**, so `enabled` is always False.
  - No rows: returns `{slope: 1.0, n: 0, fitted: False, enabled}`.
  - Otherwise returns `backtest.fit_recalibrator(resolved)` plus `enabled`. On exception: `{slope: 1.0, n, fitted: False, enabled}`.
- **Section comment, MON-1 market resolutions** (`:314-320`): `resolutions.jsonl` lives in the same dir. Its rows are `{report_id, forecast_id, market_id, resolved_outcome, model_p, market_p_at_research, brier_contribution, resolved_at, ...}`, keyed by the triple.
- **`_resolutions_file(d=None)`** (`:323-324`): returns `<d or ledger_dir()>/resolutions.jsonl`.
- **`read_market_resolutions(d=None)`** (`:327-345`): tolerant JSONL reader, same pattern as `read_ledger`.
- **`_resolution_key(report_id, forecast_id, market_id)`** (`:348-350`): joins `str(x or '')` with `\x1f` separators.
- **`_RESOLUTIONS_WRITE_LOCK = threading.Lock()`** (`:357`): serialises check-then-append within one process (LOOP-017 P1).
- **`_flock_exclusive(f)`** (`:360-366`): best-effort `fcntl.flock(LOCK_EX)`. Silently skipped on `ImportError`/`OSError`/`ValueError`.
- **`append_market_resolution(*, report_id, forecast_id, market_id, resolved_outcome, model_p, market_p_at_research, brier_contribution, resolved_at, resolved_yes_price=None, d=None)`** (`:369-420`):
  - Strips the ids and returns None if any is empty (`:384-388`).
  - Entry (`:390-401`): the fields above plus `resolved_yes_price` and `schema_version: 1`.
  - Under the thread lock it opens the file in `"a"` mode, takes the flock, **re-reads the whole file**, builds the key set, and returns None on a duplicate. Otherwise it writes and flushes one line (`:405-417`). The lock is released when the `with` block closes the file.
  - Returns the entry, or None on `OSError`. Each append costs a full re-read, so the work grows with the file (O(n)).
- **`market_brier_summary(d=None, entries=None)`** (`:423-436`): `n_resolved = len(records)` counts all records, including those whose `brier_contribution` is None. `mean_brier` is the mean of the numeric `brier_contribution` values, rounded to 4 dp, or None.

### 2. `backend/app/services/ensemble.py`

Docstring (`:1-9`): pure aggregation of N structured forecasts. The N-run driver is described as living in `scripts/forecast_tools.py`; in production it lives in the orchestrator's `_maybe_run_seed_ensemble`.

- **`_cfg(name, default)`** (`:18-24`): `getattr(Config, name, default)`. Never raises.
- **`_norm_name(name)`** (`:27-29`): lowercase, replace each run of characters that are not `\w` or CJK U+4E00–U+9FFF with a space, collapse whitespace, strip. This is the shared scenario-name key, also imported by `backtest.py:18`, `forecast_extractor.py:3049,3278,3738`, `backend/scripts/scheduled_rerun.py:70` and `drf2/driver/ensemble.py:19-25`.
- **`_scenario_tokens(text)`** (`:32-42`): tokens for semantic matching. Latin tokens match `[a-z0-9][a-z0-9.%$]*`; every CJK character is its own token; single-character Latin tokens are dropped.
- **`_token_overlap(a, b)`** (`:45-52`): Jaccard similarity. Returns 0 if either set is empty or they do not intersect.
- **`align_scenario_buckets(runs, min_overlap=None)`** (`:55-115`), W9-5:
  - `min_overlap` defaults to `float(Config.ENSEMBLE_ALIGN_MIN_OVERLAP or 0.34)`. A configured 0 therefore becomes 0.34 (`:68-72`).
  - For each run index `ri` and each dict scenario with a non-empty normalised name:
    - Exact-name hit: use `by_name[key]`.
    - Otherwise, if the scenario has criteria tokens: pick the existing bucket with the highest Jaccard, **skipping buckets that already contain run `ri`** (the same-run guard), and accept it if the score is ≥ `min_overlap` (`:86-96`).
    - Otherwise start a new bucket `{name, names, criteria, tokens, entries: [(ri, s)], runs: set}`.
  - Bucket tokens grow by union as scenarios join (`:109`). Each alias name is recorded with `by_name.setdefault` (`:114`).
  - Returns buckets in first-seen order. The algorithm is greedy and depends on input order.
- **`_extremized_logodds(probs, a, eps=1e-6)`** (`:118-136`): `sigmoid(a · mean(logit(clamp(p, eps, 1−eps))))`. Unparseable probabilities are skipped. `z` is clamped to ±50. Returns 0.0 when nothing parses.
- **`_mean`** (`:139-140`) returns 0.0 for an empty list. **`_stdev`** (`:143-147`) is the sample stdev (n−1) and returns 0.0 when n < 2.
- **`aggregate_forecasts(forecasts)`** (`:150-258`):
  - `n = 0` returns `{n_runs: 0, scenarios: [], agreement: None, schema_version: 1}` (`:162-165`).
  - **Semantic path**, used when `ENSEMBLE_SEMANTIC_ALIGN` is truthy (default true, `config.py:340`). Buckets come from `align_scenario_buckets`. For each bucket it collects `float(probability or 0.0)`, a set of `key_drivers`, the first non-empty `resolution_criteria`, and `aliases` (`:170-184`).
  - **Legacy path** (`:185-202`): bucket by exact `_norm_name` only.
  - `a = float(Config.ENSEMBLE_EXTREMIZE_A)`, or None if the attribute is missing or unparseable (`:206-210`). **Config always defines it, default 1.0 (`config.py:333`).** By default this is therefore geometric log-odds pooling with a = 1, not the arithmetic mean.
  - Per bucket row (`:213-233`):
    - `mean_probability` (diagnostic), `stdev`, `min`, `max`.
    - `support = len(probs)`. This counts entries, not distinct runs.
    - `support_ratio = support/n` (3 dp), `key_drivers` (sorted, first 8), `resolution_criteria`, and `aliases` when there is more than one.
    - `_point` is the extremized pool when `a` is set, else the mean. Missing runs are **not** counted as zero: the mean covers only the runs that surfaced the scenario.
  - Renormalises the `_point` values to sum to 1 as `probability` (4 dp). Sets `p_low`/`p_high` to probability ± stdev, clipped to [0,1]. `pooling` is `"extremized_logodds"` or `"arithmetic_mean"`. Rows are sorted by probability, descending (`:235-244`).
  - Returns (`:246-258`): `{n_runs, scenarios, agreement: _ensemble_agreement(runs, buckets=aligned), agreement_spread: max(0, 1 − 2·mean(stdev)) (3 dp), semantic_alignment, extremize_a, headline, horizon (from runs[0]), schema_version: 1}`.
- **`pool_binary_forecasts(primary, secondary, *, primary_model="primary", extremize_a=None, spread_threshold=0.15)`** (`:261-345`), ITEM 12 multi-model pooling. It **mutates `primary` in place**.
  - Returns `[]` when there are no dict primaries or `secondary` is empty.
  - The match key is `forecast_extractor._binary_key`, which lowercases and collapses `\W+`. There is an inline fallback if the import fails (`:280-284`).
  - For each secondary model it indexes probabilities by statement key and by `id`, first occurrence wins, unparseable values skipped (`:287-304`).
  - For each primary with a parseable probability, it matches each model by statement key first, then by id (`:321-329`). With no match it leaves the primary unchanged.
  - Otherwise `pooled` is the extremized pool if `a` is set, else the mean, and `spread` is the sample stdev. It sets `b["ensemble"] = {models, probs (4 dp), pooled (4 dp), spread (4 dp)}` and `b["probability"] = round(pooled, 2)` (`:332-340`).
  - Appends the forecast's id to the returned low-agreement list when `spread > spread_threshold` (`:341-344`).
  - Secondary probabilities are not range-checked. The logit pool clamps them; the arithmetic mean would not.
- **`_ensemble_agreement(runs, buckets=None)`** (`:348-419`), R2-CAL-9:
  - Returns None for empty `runs`.
  - With `buckets`: builds each run's distribution over `b{bi}`, summing probabilities floored at 0, then normalising (`:367-383`). Fewer than 2 run distributions returns **1.0**. Fewer than 2 buckets supported by at least 2 runs returns **None** (`:384-388`).
  - Legacy path: builds distributions over `_norm_name` keys (`:389-408`).
  - Then computes `agreement = (1 − mean pairwise TV distance) × mean presence ratio over all keys`, clipped to [0,1] and rounded to 3 dp (`:409-419`).

### 3. `backend/app/services/backtest.py`

Docstring (`:1-11`): pure scoring. A "resolved forecast" is `{forecast, outcome}` where `outcome` is the name of the realised scenario.

- **`_cfg`** (`:21-27`): same as in ensemble.
- **`_scenario_prob(s)`** (`:30-38`): first parseable value of `probability`, then `mean_probability`; else 0.0. This lets ensemble outputs be scored too.
- **`score_forecast(forecast, outcome)`** (`:41-70`):
  - No scenarios: returns `{error: "no scenarios", brier: None, realized_probability: None}`.
  - `target = _norm_name(outcome)`; `matched = target in names`.
  - Brier is Σ (p − y)² over the scenarios, with y = 1 for **every** scenario whose normalised name equals the target. `realized_p` is the probability of the last match.
  - `log_loss = −ln(clamp(realized_p, 1e-9, 1))`, but only when `matched`; else None.
  - Returns `{brier (4dp), realized_probability, log_loss, outcome_matched_a_scenario, n_scenarios}`.
  - An outcome that matches no scenario still gets a Brier of Σ p_i², which is less than or equal to any matched Brier for the same vector (see Surprises).
- **`calibration_report(resolved, bins=5)`** (`:73-185`):
  - Keeps items whose `forecast` is truthy. Returns `{n: 0, mean_brier: None, bins: [], calibration_error: None}` when there are none.
  - Bin edges are `i/bins`. Each scenario probability goes to bin `min(bins−1, max(0, int(p·bins)))`, with a hit when its normalised name equals the outcome (`:86-103`).
  - Per non-empty bin (`:116-145`):
    - `mean_predicted`, `observed_hit_rate`.
    - Jeffreys-smoothed rate `(hits+0.5)/(n+1)`.
    - Normal-approximation credible interval: smoothed rate ± 1.96·√var(Beta(hits+0.5, n−hits+0.5)), clipped to [0,1].
  - Empty bins report Nones.
  - `calibration_error` is the count-weighted mean of |mean_pred − hit_rate| (`:147-149`).
  - Murphy decomposition `{reliability, resolution, uncertainty, brier_pooled}` (`:152-171`). `brier_pooled` is per prediction (Σ(p−y)²/N over every scenario), which is a different scale from `mean_brier`, the mean of per-forecast multi-class sums.
  - `insufficient_data = bool(CAL_MIN_RESOLVED and n < CAL_MIN_RESOLVED)` (`:174-175`). **`CAL_MIN_RESOLVED` is not a Config attribute**, so this is always False in production.
  - Returns `{n, mean_brier, calibration_error, brier_decomposition, resolution, insufficient_data, bins}`.
  - `bins=0` would raise ZeroDivisionError at `:86`. Callers pass 5 or `--bins`.
- **`fit_recalibrator(resolved)`** (`:188-227`), R2-CAL-5:
  - Builds (logit(p), y) for **each scenario**, with p clamped to [1e-6, 1−1e-6].
  - Fewer than 10 points returns `{slope: 1.0, n, fitted: False}`.
  - Otherwise runs 500 iterations of gradient descent on log-loss for slope `s` in `sigmoid(s·x)`, with lr 0.05, the gradient averaged over points, and `s` clamped to [0.1, 5.0] after each step.
  - Returns `{slope (4dp), n, fitted: True}`.
- **`apply_recalibration(prob, slope, eps=1e-6)`** (`:230-237`): `sigmoid(slope·logit(p))`, z clamped to ±50. Returns the input unchanged on error. It does not renormalise across scenarios. **It has no production caller.**

### 4. `backend/app/services/resolution_autorun.py`

Docstring (`:1-13`): this is an in-process scheduler for `scripts/resolution_monitor.py`. It is off by default, and only `run.py` starts it.

- Module state (`:26-30`): logger `mirofish.resolution_autorun`, `_RUN_TIMEOUT_SECONDS = 900`, `_inflight_lock`, `_inflight = False`.
- **`_script_path()`** (`:33-35`): returns `<backend>/scripts/resolution_monitor.py`, where `<backend>` is three dirnames up from this file.
- **`_run_once()`** (`:38-60`):
  - Returns `{ok: False, error: "...not found"}` if the script is missing.
  - Otherwise runs `subprocess.run([sys.executable, script, "run", "--all-recent"], capture_output=True, text=True, timeout=900, cwd=<backend>/scripts)`.
  - On `TimeoutExpired` it logs an error and returns `{ok: False, error: "timeout"}`; `subprocess.run` kills the child.
  - On `OSError` it returns `{ok: False, error}`.
  - A non-zero return code logs a warning with the last 500 characters of stderr (or stdout) and returns `{ok: False, returncode, tail}`.
  - Success returns `{ok: True, returncode: 0}`.
- **`trigger_once()`** (`:63-80`): under the lock, returns False if a run is in flight; otherwise sets the flag and starts a daemon thread named `resolution-monitor-once`. That thread runs `_run_once()` and clears the flag in `finally`. Returns True. The `_run_once` result dict is discarded.
- **`is_inflight()`** (`:83-85`): reads the flag under the lock.
- **`start(interval_hours=None, *, initial_delay_s=60.0)`** (`:88-117`):
  - `hours` is the argument, else `float(Config.RESOLUTION_MONITOR_AUTORUN_HOURS or 0)`.
  - `hours <= 0` returns None and nothing starts.
  - Otherwise starts a daemon thread named `resolution-monitor-autorun` with a `threading.Event`. It waits `initial_delay_s`, then loops `trigger_once()` and waits `hours·3600` s. If the event is set, the thread exits.
  - The event is exposed as `t._drf_stop_event`, and the thread is returned.
  - The log line hardcodes "首轮延迟 60s" ("first run delayed 60s") whatever `initial_delay_s` is (`:116`).

### 5. `backend/app/services/requirement_spec.py`

Docstring (`:1-11`), QUALITY-OPT F0: pure parsing of the brief into an output contract.

- **`_LANG_DIRECTIVES`** (`:18-22`), checked in order:
  1. `write (the )?(report|submission|forecast|response|answer) in english` → English
  2. `\b(in|用)\s*english\b` → English
  3. `用中文(撰写|回答|写)?|以中文(撰写|回答)?|report in chinese` → Chinese

  All are case-insensitive. The English directives come first, so English wins when both kinds are present.
- **`_cjk_ratio(text)`** (`:25-31`): CJK characters (U+4E00–U+9FFF) divided by alphabetic-or-CJK characters. Digits are not counted.
- **`detect_output_language(*texts)`** (`:34-45`): joins the non-empty texts. The first matching directive wins. Otherwise it returns `"Chinese"` when the CJK ratio is ≥ 0.10, else `"English"`.
- **`_parse_binary_min(text)`** (`:48-64`): returns `max(1, n)` from the first of four regexes that matches:
  - `(\d{1,2})\s*\+?\s*binary`
  - `minimum of N binary`
  - `at least N (binary|yes/no|forecasts)`
  - `N+ (yes/no|yes-no) forecasts`

  Returns None otherwise. The first regex has no left boundary (see Surprises).
- **`_parse_page_budget(text)`** (`:67-82`): matches `N pages or less`, `(aim for|under|max(imum)?( of)?|<=?) N pages`, or `N pages (total|maximum|max)`, and returns `max(1, N)`.
- **`parse_requirement_spec(brief_text, research_report=None)`** (`:85-105`):
  - `themes` collects `"mercantilism"` (substring `mercantilis`), `"ai"` (`\bai\b` or "artificial intelligence") and `"intersection"` (substrings `intersection`, `collid` or `intersect`).
  - Returns `{output_language: detect_output_language(brief, research_report), wants_binary: bool(binary_min) or regex binary|yes/no|yes-no, binary_min_count, page_budget, themes}`.

### 6. `backend/app/services/research_progress.py`

Docstring (`:1-12`): monotonic progress estimated from bridge milestones, plus bounded tail and exact full-history log snapshots.

- **Regexes** (`:23-44`):
  - `_TRACK_DIR_RE ^track_(\d+)$`
  - `_ISO_PREFIX_RE`, which splits `<iso> rest`
  - `_LEADING_EVENT_RE`, an optional ISO timestamp then `[kind]`
  - `_ADAPTIVE_GAP_RE research:deep-adaptive-gap-N`
  - `_COVERAGE_TOPUP_RE research:deep-coverage-topup-N`
  - `_V3_EVENT_RE`: `[kind] research:v3:<phase><detail>`; the phase must open the message
  - `_V3_UNIT_COUNT_RE \((\d+)\s+(kiqs?|groups?)\b`
  - `_V3_GAP_ROUND_RE ^round\s+(\d+)`
  - `_V3_UNIT_ID_RE ^[A-Za-z]{1,3}\d+[A-Za-z0-9]*$`
- **Kinds** (`:45-47`): `_V3_ENTER_KINDS {stage, resume}`, `_V3_FINISH_KINDS {ok, done}`, `_LIFECYCLE_KINDS {init, stage, ok, done, resume}`.
- **v3 bands** (`:51-65`):

  | Phase | Band |
  |---|---|
  | plan | 6–10; done 9–10 |
  | gather | 10–60 |
  | gap | round 1 = 60–64; round 2+ = 64–68 (floor capped at 64) |
  | synthesize | 70–86; done 86–88 |
  | qa | 88–90; done 89–90 |
  | finalize | 90–91 |
  | `wrote sources.json` | v3 92–93; legacy 95–96 |

- **Limits** (`:67-72`): `MAX_PROGRESS_TRACKS = 16`, `MAX_PROGRESS_ATTEMPTS = 16`, `MAX_PROGRESS_LINES = 500`, `MAX_TAIL_BYTES_PER_FILE = 256 KiB`, `MAX_PROGRESS_LINE_CHARS = 1200`, `MAX_FULL_PROGRESS_TOTAL_BYTES = 64 MiB`.
- **`ResearchProgressLimitError(ValueError)`** (`:75-76`). **`ProgressTail`**, a frozen dataclass `{lines, source_count, truncated}` (`:79-85`). **`_V3Event`** `{kind, phase, detail}` (`:88-94`).
- **`_parse_v3_event(line)`** (`:97-106`): returns a lowercased `_V3Event` only when the line matches `_V3_EVENT_RE` and its kind is a lifecycle kind.
- **`_v3_milestone(event)`** (`:109-144`): maps the phase and kind to a band, per the table above.
  - `gap` uses the round number from `detail`; round ≥ 2 shares the 64–68 slot.
  - A unit completion such as `[ok] research:v3:gather K3` is **not** a milestone (it returns None).
  - Unknown phases return None and never fall through to the legacy rules.
- **`class ResearchProgressEstimator`** (`:147-368`), `_ACTIVITY_SCALE = 80.0`:
  - `__init__` (`:164-174`): progress 2, band 2–4, events 0, v3 flags reset.
  - `_advance_phase(floor, ceiling)` (`:180-197`): clamps to [2,99]. A higher floor opens a new band: it resets the event count and the unit ledger and returns True. An equal floor widens the ceiling. A lower floor is ignored. Progress becomes `max(progress, floor)`. Progress never decreases.
  - `_arm_v3_units(event)` (`:199-204`): for an enter-kind event whose detail includes `(N KIQs|groups`, it records the phase and total unit count.
  - `_record_v3_unit(event)` (`:206-220`):
    - Applies only to `ok` events of the armed phase, with a non-`done` detail.
    - The unit key is the first token if it looks like a unit id, else the whole detail.
    - Advances progress to `floor + min(span−1, int((span−1)·done/total))`.
  - `_milestone(line, *, v3=False)` (`:222-343`), a static method:
    - **Gate:** the line must start with a lifecycle `[kind]`; otherwise None. This means tool/result text such as a web page saying "research complete" can never cross a phase boundary (`:230-235`).
    - v3 lines are classified only by `_v3_milestone` (`:237-239`).
    - Otherwise it applies ordered substring rules on the lowercased line:
      - Finalize, most specific first: `research complete` 99/99; `research charts:` or `wrote charts.json` 98–99; `actor-ontology` → None (Track B suppressed); triangulation rewrote/adopted 97–98; triangulation verifying 95–97; `research_quality=` 95–96; `wrote sources.json` (v3 or legacy slot); timeline/quantitative 94–95; actors 93–95; extract 92–94; `wrote research_report.md` 91–92; judge pass 90–91; judge/refine round 88–90; synthesize produced 87–89; multipart writing 82–87; outline parsed 80–84; requesting/writing report 78–84.
      - Deep protocol: gap-closing converged/unchanged/ceiling 77–78; adaptive gap N (N clamped 1..6) = (69+N)..min(77, 71+N); coverage topup N (N clamped 1..4) = 67+2N(+1 when "turn complete"); `coverage gate` (not `/standard`) 69–72; deep-5 complete 68–69; deep-5 60–68; parallel-phase-merge complete 58–60; merge 53–58; "deep: running … middle phases" 42–53; deep-1-scope complete 40–42; scope 34–40; fanout-merge complete 32–34; fanout-merge 28–32; `deep fan-out:` or `research:fanout:` 18–32; deep-opening complete 16–18; opening 8–16; `deep: starting multi-pass` or `dual-track:` 6–8.
      - Quick/standard: `coverage gate/standard` 68–78; standard-coverage-topup 58–68; `research: turn complete` 62–68; `research: starting agent turn` 10–62; `[init]` 4–6.
  - `observe(line)` (`:345-368`):
    - Parses a v3 event and sets `_v3_seen`.
    - If the line is a milestone, advances the phase, and arms units when a v3 band newly opened. Otherwise, for a v3 event, records a unit completion.
    - Any line containing `[tool]` or `[result]` (a substring check) increments the event count and moves progress to `floor + min(span−1, int(span·(1−exp(−events/80))))`.
    - Returns the int progress.
- **`aggregate_parallel_progress(track_progress, *, previous=2, ceiling=95, excluded_indices=())`** (`:371-392`):
  - Takes the arithmetic mean (floored to int) of the non-excluded tracks, each clamped to [0, ceiling], and returns `max(previous, min(ceiling, mean))`.
  - With every track excluded it returns `clamp(previous, 0, ceiling)`.
- **`_tail_lines(path, limit)`** (`:395-415`):
  - Refuses symlinks and non-files.
  - Reads the last ≤256 KiB and drops the leading partial line when starting mid-file. Decodes UTF-8 with `replace`.
  - Keeps the last `limit` lines, each trimmed to 1200 characters.
  - `truncated = read_size < size or len(decoded) > limit`. Returns `([], False)` on `OSError`.
- **`_progress_sources(handoff_dir, *, require_all_tracks=False)`** (`:418-467`): collects sources in order.
  - Root `research_progress.log` gets order 0 and an empty label.
  - `track_N/research_progress.log` dirs, sorted numerically, capped at 16, get order 1..k (the enumerate index, not N) and label `track:N`.
  - `research_attempts/*.log` files (names `[A-Za-z0-9_-]+`), sorted by name and capped at 16, get the following order numbers and label `attempt:<stem>`.
  - Symlinked dirs and files are rejected.
  - In full mode, more than 16 track dirs or attempt logs raises `ResearchProgressLimitError`.
- **`_merge_progress_rows(batches, *, deduplicate)`** (`:470-497`):
  - A line with an ISO timestamp renders as `"<ts> [label] rest"` and sorts by `ts`.
  - A continuation line without a timestamp renders as `"[label] line"` and inherits the previous timestamp, or `""` so an orphan sorts first.
  - Sorts by (ts string, source_order, ordinal).
  - Dedup key is `(source_order, line)`, applied only when `deduplicate` is set.
- **`merged_research_progress_tail(handoff_dir, limit=200)`** (`:500-517`): clamps `limit` to [1,500], tails each source, merges with dedup, and keeps the last `limit` lines. Returns `ProgressTail(lines, source_count=len(sources), truncated)`.
- **`merged_research_progress_full(handoff_dir, *, max_total_bytes=64 MiB)`** (`:520-564`):
  - Uses `require_all_tracks=True`.
  - For each source it fstats the size and raises `ResearchProgressLimitError` when the cumulative total would exceed the limit.
  - Reads exactly `size` bytes; a short read raises `RuntimeError("…changed during full-history snapshot")`, and so does any `OSError`.
  - Lines are not trimmed and not deduplicated. Returns `truncated=False`.

### 7. `backend/app/utils/prediction_markets.py`

Docstring (`:1-20`): this is a keyless Polymarket Gamma client. Market prices serve as calibration anchors, not truth. The anchor-eligibility rules are: `closed` is the gate, because `active` stays True after resolution; P(yes) is the `"Yes"` index of `outcomePrices`; the price must lie strictly inside (0,1); volume must be ≥ 200; results are deduplicated and sorted by volume, descending. Imports: `httpx`, `json`, `logging`, `random`, `re`, `time` (`:22-31`).

- **Constants** (`:35-57`):
  - `POLYMARKET_BASE_URL = https://gamma-api.polymarket.com`, `CLOB_BASE_URL = https://clob.polymarket.com`
  - `_TRANSIENT_STATUS {429, 500, 502, 503, 504}`
  - `_BROWSER_UA`, a Chrome-like UA string used to get past Cloudflare
  - `_RESOLVED_PRICE_HI = 0.99`, and `_RESOLVED_PRICE_LO = 0.01`, which is **never used**
- **`_backoff_sleep(attempt)`** (`:50-52`): sleeps `min(2.0, 0.5·attempt) + U(0, 0.5)` s.
- **`_cfg`** (`:60-66`). **`_coerce_float`** (`:69-77`) treats NaN as None. **`_as_list`** (`:80-91`) accepts a list or a JSON-string list, else `[]`.
- **`_extract_json_payload(text)`** (`:94-117`): takes the first fenced ```json block if present, then tries `json.loads`, then the outermost `[...]`, then `{...}`. Returns None on failure.
- **`_yes_price(outcomes, prices)`** (`:120-129`): returns the price at the case-insensitive `"yes"` index. Returns None on a length mismatch or when there is no Yes outcome.
- **`_fresh_yes_price(raw)`** (`:132-143`): returns None when the market is closed or the price is None or outside (0,1). There is no volume filter.
- **`_parse_resolution(raw)`** (`:146-184`):
  - Returns None for a non-dict.
  - `closed` is `True`, or the string `"true"`.
  - `uma_status` comes from `umaResolutionStatus`, falling back to `umaResolutionStatuses`.
  - `resolved_outcome` is the first outcome whose price is ≥ 0.99.
  - `resolved = closed and resolved_outcome is not None`.
  - Returns `{market_id, closed, resolved, resolved_outcome, resolved_yes_price (4dp|None), uma_status}`.
- **`_cap_per_event(ranked, max_per_event, max_total)`** (`:187-206`): caps each `event_title` (falling back to `market_id`) at `max_per_event` markets, then truncates the list to `max_total`. `max_per_event <= 0` removes the per-event cap.
- **`class PolymarketClient`** (`:209-562`):
  - `__init__(base_url, timeout=10.0)` (`:218-222`): sets `last_error = None` and `transport_errors = {}`.
  - `enabled` property (`:224-227`): `Config.PREDICTION_MARKETS_ENABLED`, default True.
  - **`_request(url, params)`** (`:230-269`):
    - At most two attempts. On attempt 1 a transient status sleeps and retries; `httpx.TransportError` also sleeps and retries.
    - Any other exception, including `raise_for_status` on 4xx, a transient status on the second attempt, or JSON decode errors, breaks out with no retry.
    - On failure it records `last_error = {error_class, http_status, url}`, increments `transport_errors["Class[:status]"]`, logs a warning and returns None.
    - Headers are `Accept: application/json` and the browser UA.
  - `_get(path, params)` (`:271-273`): GETs `base_url + path`.
  - **`search_events(query, limit=15)`** (`:276-286`): `GET /public-search?q=…&limit_per_type=limit&events_status=active`. Returns the dict events, or `[]` when disabled, given a blank query, or on failure.
  - **`snapshot_for_queries(queries, per_query=None, max_total=20, min_volume=200, max_per_event=3, llm_call=None, question="")`** (`:289-336`):
    - `per_query` defaults to `Config.PREDICTION_MARKETS_PER_QUERY` (15).
    - For each query and each event it normalises every market and deduplicates by `market_id`; the first query to hit a market is recorded as its `matched_query`.
    - Sorts by volume, descending, and applies `_cap_per_event`.
    - When both `llm_call` and `question` are given, filters through `score_market_relevance`.
  - **`requote_markets(markets)`** (`:339-388`):
    - Shallow-copies each row and never drops one.
    - Sets `price_at_research` to the existing `price_at_research`, else the old `implied_yes_prob` (idempotent).
    - With a fresh valid price: overwrites `implied_yes_prob`, removes `requote_failed`, and sets `price_delta`.
    - Otherwise: sets `requote_failed = True` and removes `price_delta`.
    - Fetching is skipped when the client is disabled.
  - **`_fetch_fresh_markets(ids)`** (`:390-417`):
    - Chunk size is `Config.PREDICTION_MARKETS_REQUOTE_CHUNK`, default 20. **That attribute is not defined in `config.py`.** Values ≤ 0 become 20.
    - Calls `GET /markets?id=a&id=b…`; httpx encodes the list as repeated params.
    - Accepts a list, `{markets: []}` or `{data: []}`. Returns `{id: raw}`; a failed chunk is simply missing.
  - **`fetch_price_history(clob_token_id, interval="1d", days=90)`** (`:420-462`):
    - Calls `GET clob /prices-history?market=<token>&interval=<interval>` and accepts `{history: []}` or a bare list.
    - Drops points older than `now − days·86400` and points with an unparseable `t` or `p`.
    - Returns `[{t: int, p: 4dp}]`. **There is no production caller in the backend**; the bridge has its own mirror.
  - **`fetch_resolutions(market_ids)`** (`:465-500`): deduplicates the ids, then runs `_fetch_fresh_markets` and `_parse_resolution` on each result. Returns `{}` when disabled or given empty input.
  - **`_normalize_market(raw, matched_query, event_title="", min_volume=200, event_slug="")`** (`:502-562`), a static method:
    - Returns None when `id` or `question` is missing, the market is closed, the Yes price is missing or outside (0,1), or `volume < min_volume`.
    - Output fields: `{market_id, exchange: "polymarket", question, implied_yes_prob (4dp), volume, liquidity, event_title (or groupItemTitle), matched_query}`.
    - Optional fields, only when the source has them: `url` = `https://polymarket.com/event/<slug>`, `end_date`, `one_day_price_change`, `best_bid`, `best_ask`, `outcomes`, `clob_token_ids`, and `clob_yes_token_id`.
    - `clob_yes_token_id` is looked up by the Yes index, as a guard against reversed tokens (LOOP-017 P1); it is omitted when the index is out of range.
- **`_esc_cell(x)`** (`:566-568`): replaces `|` with `／` and newlines with spaces.
- **`_requote_move(m)`** (`:571-577`): returns `"34%→41%"` when the research-time and current prices differ at 4 dp, else None.
- **`render_markets_block(markets, lang="en")`** (`:580-626`):
  - Deterministic markdown under the title `### Prediction Market Signals (Polymarket)`.
  - Headers are localised for `zh*` or English: #, question, venue, implied P(yes), an optional Δ column (only when some row moved), and volume.
  - The question is truncated to 160 characters and linked when a `url` exists. A caveat line follows the table.
  - Returns `""` for an empty input.
- **Query derivation**:
  - `_QUERY_STOPWORDS` (`:633-642`), `_QUERY_TOKEN_RE` (words, 4-digit years, CJK runs of 2+ characters, `:646`), `_QUERY_GENERIC_BLACKLIST` (`:650-653`), `_CLAUSE_SPLIT_RE` (`:657`).
  - **`_salient_phrases(text, max_words=3)`** (`:660-696`): phrases never span clauses. A CJK token is truncated to 12 characters and flushes the current phrase. Stopwords, blacklisted words and short non-uppercase words act as phrase breaks. Phrases are deduplicated case-insensitively, preserving order.
  - **`derive_market_queries(question, hot_topics, actor_names, max_queries=12, max_words=5)`** (`:699-733`): actors are the first 3. `reserved = min(2, len(actors))` slots are kept for actors. Question phrases (first 6) and hot topics (first 6) are capped at `max_queries − reserved`; actor names may fill up to `max_queries`.
- **`_LLM_QUERY_MIN = 10`, `_LLM_QUERY_MAX = 16`** (`:738-739`). **`_clean_query(q, max_words=8)`** (`:742-746`).
- **`derive_market_queries_llm(llm_call, question, hot_topics, actors)`** (`:749-806`):
  - Precomputes the heuristic `fallback`, which it returns if `llm_call` is None or not callable, or if the question is blank.
  - The prompt asks for 10–16 short queries phrased like market titles, as a JSON array.
  - Accepts a `{queries: []}` wrapper and items that are strings or dicts with `query`, `q` or `title`. Returns at most 16.
  - An empty result returns `fallback`; a short result is padded from `fallback` up to 10. On any exception it logs a warning and returns `fallback`.
- **`score_market_relevance(llm_call, question, markets, min_relevance=None)`** (`:810-884`):
  - One batch LLM call that scores each market 0–10. The threshold is `Config.PREDICTION_MARKETS_MIN_RELEVANCE`, default 5.
  - Accepts the `{scores|markets: []}` wrappers and the `id` or `relevance` aliases. Scores are clamped to [0,10] and the rationale to 200 characters.
  - Rows below the threshold are dropped. Rows with no score are **kept**. Scored rows get `relevance_score` (1 dp) and `relevance_rationale`.
  - Sorts by (score, defaulting to the threshold, then volume), both descending.
  - An unparseable response or an exception returns the input rows unchanged.

---

## Control flow

1. **Research progress (RESEARCH stage).**
   - `PipelineOrchestrator` creates a `ResearchProgressEstimator` for each research subprocess (`pipeline_orchestrator.py:2477`). It calls `estimator.observe(line)` for every stdout line (`:2496`) and passes `local` to `on_progress` on tool/result/stage/ok/done/error lines (`:2497-2530`).
   - With parallel tracks, each track callback clamps its progress to ≤ 95 and publishes `aggregate_parallel_progress(track_local, previous=last_published, ceiling=95, excluded_indices=failed_tracks)` (`pipeline_orchestrator.py:11137-11159`). A failed track is added to `failed_tracks` (`:11259-11260`).
   - The UI polls `GET /api/research/<id>/progress?scope=tail&lines=N` (`frontend/src/api/research.js:230-236`). That calls `merged_research_progress_tail`, or `merged_research_progress_full` when `scope=full` (`backend/app/api/research.py:895-900`); a limit error returns 413 (`:918-919`).
   - The demo exporter calls `merged_research_progress_full` (`backend/scripts/export_demo_site_data.py:125`).
2. **Requirement spec (REPORT stage).**
   - `ReportAgent.__init__` sets `output_language` to `REPORT_OUTPUT_LANGUAGE` from the environment, or else `detect_output_language(simulation_requirement, research_report, situation_brief)` (`report_agent.py:1594-1603`).
   - `_report_shape` uses `page_budget` (`:1737-1742`).
   - Binary themes come from `parse_requirement_spec(...).themes` when `FORECAST_BINARY_THEMES` is empty (`:3057-3063`).
   - The binary minimum is `max(Config.BINARY_FORECASTS_MIN_COUNT, spec.binary_min_count)` (`:8723-8736`).
   - The compact-synthesis word cap is `max(600, min(2800, page_budget·150))` (`:8779-8787`).
   - The translation-direction sniff uses `detect_output_language(md)` (`:6094-6095`).
3. **Prediction markets (REPORT stage).**
   - `_build_market_pack` (`report_agent.py:2765-2778`) calls `_load_prediction_markets` (`:2570`):
     - (a) It reads `handoff/prediction_markets.json`, written by the bridge, takes the first `PREDICTION_MARKETS_MAX` rows, and calls `_requote_snapshot`, which calls `PolymarketClient.requote_markets` (`:2581-2601, :2689-2721`).
     - (b) Otherwise it does a live fetch: `derive_market_queries_llm`, then `snapshot_for_queries`, then `score_market_relevance`. It keeps **only rows that have a `relevance_score`** (fail-closed) and persists `prediction_markets_recovered.json` (`:2610-2687`).
   - `_render_market_pack` calls `render_markets_block(rows[:20])` (`:2739-2763`).
   - Before binary extraction, `_refresh_market_prices_for_extraction` re-quotes again (`:2723-2737`).
4. **Binary multi-model ensemble (REPORT stage).** When `FORECAST_ENSEMBLE_MODELS` is non-empty, `forecast_extractor` draws binaries from each secondary model and calls `pool_binary_forecasts(binaries, secondary, primary_model, extremize_a=Config.ENSEMBLE_EXTREMIZE_A, spread_threshold=FORECAST_ENSEMBLE_SPREAD_THRESHOLD)` before market anchoring (`forecast_extractor.py:2806-2834`).
5. **Ledger (end of REPORT).** In `ReportAgent.generate_report` (`report_agent.py:11113`), then `_finalize_structured_forecast` (`:11502`):
   - If `REPORT_FORECAST_LEDGER` is set, it calls `calibration_summary()`. Only when `n_resolved > 0` does it add `forecast["historical_calibration"]` and append a note to `confidence_rationale` (`:3181-3192`).
   - It writes `forecast.json` atomically (`:3194-3195`).
   - Then it calls `append_forecast(forecast, report_id, horizon, created_at=now)`, without `objective_signals` (`:3197-3204`).
6. **Seed ensemble (after REPORT).** `_maybe_run_seed_ensemble` (`pipeline_orchestrator.py:8529`):
   - Gate: `n_seeds > 1` (default 1), full mode, structured forecast on, not already done.
   - It runs the extra seeds; each seed's `generate_report` also appends to the ledger.
   - With at least 2 forecasts it calls `aggregate_forecasts` (`:8717-8718`) and sets `confidence = _agreement_to_confidence(agreement)`: ≥ 0.75 is high, ≥ 0.45 medium, otherwise low, and None maps to medium (`:8489-8499`).
   - It writes `ensemble_forecast.json` to the handoff dir and the report folder (`:8729, 8736`) as a sidecar; the sealed `forecast.json` is not modified.
7. **Resolution monitoring (out of band).**
   - `run.py:41-42` calls `resolution_autorun.start()`, which runs only if `RESOLUTION_MONITOR_AUTORUN_HOURS > 0`.
   - `POST /api/research/resolution-monitor/run` calls `trigger_once()` and returns 202 or 409 (`research.py:342-352`; frontend `runResolutionMonitor`, `frontend/src/api/research.js:220-222`).
   - The subprocess `resolution_monitor.py run --all-recent` creates a `PolymarketClient` (`backend/scripts/resolution_monitor.py:508`) and calls `requote_markets` and `fetch_resolutions` (`:521, :536`).
   - `build_resolution_records` sets y = 1 when `resolved_yes_price` is ≥ 0.5 and computes Brier = (model_p − y)² (`:260-295`).
   - It then calls `append_market_resolution` for each record (`:560-569`), followed by `calibration_summary` and `market_brier_summary` (`:573-574`).
8. **Manual resolution and backtest.**
   - `POST /api/v1/resolve/<report_id>` is only registered when `API_V1_ENABLED` (`backend/app/__init__.py:210-212`; default False, `config.py:388`). It gates on publishability, calls `score_forecast`, and writes `<report folder>/resolved.json` (`backend/app/api/sdk.py:283-344`). It does **not** touch `ledger.jsonl`.
   - The `forecast_tools.py backtest <file>` CLI runs `calibration_report` and `score_forecast` over a user-supplied JSON list (`backend/scripts/forecast_tools.py:49-55`).
   - `golden_eval.py` calls `append_golden_result` (`backend/scripts/golden_eval.py:377-393`) and `calibration_summary(include_evaluation=True)` (`:446-458`).

---

## Data & artifacts

| Path pattern | Format | Writer → Reader | Key fields |
|---|---|---|---|
| `<ledger_dir>/ledger.jsonl`. Default `backend/uploads/pipelines/_forecast_ledger/ledger.jsonl` (`forecast_ledger.py:23-35`, `config.py:1581`). | JSONL, append | `append_forecast` (`:66`) → `read_ledger` (`:212`), `calibration_summary`, `due_for_resolution`, `recalibration_param` | `report_id, horizon, resolution_date, created_at, scenarios[{name, probability, resolution_criteria}], confidence, resolved, outcome, schema_version, [objective_signals]` |
| `<parent>/_evaluation_ledger/ledger.jsonl` (`:38-46`) | JSONL | `append_golden_result` (redirected) → `golden_eval.py` | adds `golden, question_id, category, question, as_of_date, record_class:"evaluation", characterization_only:true, ledger_redirected` |
| `<ledger_dir>/resolutions.jsonl` (`:323-324`) | JSONL, idempotent append under flock | `append_market_resolution` (`:369`) ← `resolution_monitor.py:560` → `market_brier_summary` | `report_id, forecast_id, market_id, resolved_outcome, resolved_yes_price, model_p, market_p_at_research, brier_contribution, resolved_at, schema_version` |
| `handoff/research_progress.log`, `handoff/track_N/research_progress.log`, `handoff/research_attempts/*.log` | text lines `<iso> [kind] msg` | DeerFlow bridge (`deerflow_bridge/deerflow_research.py:874`); attempts are copied by `pipeline_orchestrator.py:3085-3110` → `_progress_sources` (`research_progress.py:418`) | ISO prefix and leading `[kind]` |
| `handoff/prediction_markets.json` | JSON `{markets: [...], ...}` or a bare list | bridge `_collect_prediction_markets` (`deerflow_bridge/deerflow_research.py:15476`) → `report_agent.py:2593-2601`. This module only defines the normalised row schema (`prediction_markets.py:525-561`). | rows: `market_id, exchange, question, implied_yes_prob, volume, liquidity, event_title, matched_query, url, end_date, outcomes, clob_token_ids, clob_yes_token_id, [price_at_research, price_delta, requote_failed, relevance_score, relevance_rationale]` |
| `<report folder>/prediction_markets_recovered.json` | JSON | `report_agent.py:2665-2681` (late live-fetch fallback) | `as_of, source:"report_fallback", queries, markets, status{}` |
| `handoff/ensemble_forecast.json` and `<report folder>/ensemble_forecast.json` | JSON | `pipeline_orchestrator.py:8729, 8736`, from `aggregate_forecasts` | `n_runs, scenarios[{name, probability, mean_probability, stdev, min, max, p_low, p_high, support, support_ratio, key_drivers, resolution_criteria, aliases?, pooling}], agreement, agreement_spread, semantic_alignment, extremize_a, headline, horizon, schema_version, n_seeds_requested, extra_runs, confidence` |
| `binary['ensemble']` (in memory, then forecast.json) | dict | `pool_binary_forecasts` (`ensemble.py:334-339`) | `models, probs, pooled, spread` |
| `<report folder>/resolved.json` | JSON | `sdk.py:344` (not part of this slice) | `report_id, simulation_id, outcome, scoring, resolved_at, forecast` |

In-memory state:
- `resolution_autorun._inflight` / `_inflight_lock` (`:29-30`), process-local.
- `forecast_ledger._RESOLUTIONS_WRITE_LOCK` (`:357`).
- `PolymarketClient.last_error` / `transport_errors` (`:221-222`), per instance.
- Estimator band and unit state (`research_progress.py:164-174`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `FORECAST_LEDGER_DIR` | `""` → `PIPELINE_DATA_DIR/_forecast_ledger` | Ledger directory. The evaluation ledger is its sibling `_evaluation_ledger`. | `config.py:278`; `forecast_ledger.py:23-31` |
| `PIPELINE_DATA_DIR` | `backend/app/../uploads/pipelines` | Base dir for the default ledger. Hardcoded, not read from env. | `config.py:1581` |
| `REPORT_FORECAST_LEDGER` | True | Gates `calibration_summary` and `append_forecast` in ReportAgent. | `config.py:277`; `report_agent.py:3181, 3197` |
| `REPORT_RECALIBRATE_FROM_LEDGER` | **not defined in Config** → False | `recalibration_param().enabled`. Setting the env var has no effect. | `forecast_ledger.py:300` |
| `CAL_MIN_RESOLVED` | **not defined in Config** → 0 | Thin-evidence flag `insufficient_data`. Setting the env var has no effect. | `backtest.py:174` |
| `ENSEMBLE_SEMANTIC_ALIGN` | true | Use semantic bucket alignment rather than exact names. | `config.py:340`; `ensemble.py:167` |
| `ENSEMBLE_ALIGN_MIN_OVERLAP` | 0.34 | Jaccard threshold for merging. A value of 0 is coerced back to 0.34. | `config.py:341`; `ensemble.py:68-72` |
| `ENSEMBLE_EXTREMIZE_A` | 1.0 | Logit pooling factor. Because it is always set, pooling is always log-odds. | `config.py:333`; `ensemble.py:206-210`; `forecast_extractor.py:2821-2825` |
| `N_FORECAST_SEEDS` | 1 | Seed-ensemble gate; must be > 1 to aggregate. | `config.py:303`; `pipeline_orchestrator.py:8539-8547` |
| `ENSEMBLE_SEED_CONCURRENCY` | 2 (clamped 1..3) | Parallel extra seeds. | `config.py:310` |
| `FORECAST_ENSEMBLE_MODELS` | `""` (off) | Secondary providers for binary pooling. | `config.py:643`; `forecast_extractor.py:2809-2811` |
| `FORECAST_ENSEMBLE_SPREAD_THRESHOLD` | 0.15 | Low-agreement cutoff for binaries. | `config.py:646`; `forecast_extractor.py:2826` |
| `RESOLUTION_MONITOR_AUTORUN_HOURS` | 0 (off) | Interval of the in-process scheduler, in hours (floats allowed). | `config.py:290`; `resolution_autorun.py:97` |
| `RESOLUTION_MONITOR_RECENT_N`, `_LOOKBACK_DAYS`, `_DRIFT_THRESHOLD` | 10 / 0 / 0.05 | Read by the monitor script only. | `config.py:282-284` |
| `PREDICTION_MARKETS_ENABLED` | true | `PolymarketClient.enabled`; ReportAgent market pack gate. | `config.py:1423`; `prediction_markets.py:224-227` |
| `PREDICTION_MARKETS_MAX` (alias `ODDPOOL_MAX_MARKETS`) | 20 | Row cap in ReportAgent (this module's `max_total` default is also 20). | `config.py:1425-1426`; `report_agent.py:2579` |
| `PREDICTION_MARKETS_MIN_VOLUME` | 200 | Passed as `min_volume` by ReportAgent. | `config.py:1428`; `report_agent.py:2651-2661` |
| `PREDICTION_MARKETS_MAX_PER_EVENT` | 3 | Passed as `max_per_event`. | `config.py:1431` |
| `PREDICTION_MARKETS_PER_QUERY` | 15 | `limit_per_type` for each search query. | `config.py:1434`; `prediction_markets.py:308-312` |
| `PREDICTION_MARKETS_MIN_RELEVANCE` | 5 | Relevance score cutoff. | `config.py:1438`; `prediction_markets.py:828-831` |
| `PREDICTION_MARKETS_REQUOTE` | true | Report-time re-quote of the snapshot. Read by ReportAgent, not by this module. | `config.py:1443`; `report_agent.py:2702` |
| `PREDICTION_MARKETS_REQUOTE_CHUNK` | **not defined in Config** → 20 | Batch size for `/markets?id=`. | `prediction_markets.py:398` |
| `BINARY_FORECASTS_MIN_COUNT` | 10 | Floor for the binary minimum; the spec can only raise it. | `config.py:318`; `report_agent.py:8724-8735` |
| `FORECAST_BINARY_THEMES` | `""` | When empty, themes come from `requirement_spec`. | `config.py:636`; `report_agent.py:3054-3063` |
| `REPORT_OUTPUT_LANGUAGE` (env only) | `""` | Overrides `detect_output_language`. | `report_agent.py:1594-1596` |
| `API_V1_ENABLED` | False | Registers `/api/v1/resolve` and the rest of `/api/v1`. | `config.py:388`; `backend/app/__init__.py:210-212` |
| `FLASK_DEBUG` → `Config.DEBUG` | False | When True, the Werkzeug reloader runs `run.py`'s module code twice (see Surprises). | `config.py:35`; `run.py:41-58` |

---

## External calls

| Call | Where | Notes |
|---|---|---|
| HTTP GET `https://gamma-api.polymarket.com/public-search` | `prediction_markets.py:280-282` | Keyless. 10 s timeout. One retry for transient errors. Browser UA. |
| HTTP GET `https://gamma-api.polymarket.com/markets?id=…` | `prediction_markets.py:405` | Batched re-quote and resolution lookups. Whether `/markets?id=` returns *closed* markets by default is **unverified**; `fetch_resolutions` depends on it. |
| HTTP GET `https://clob.polymarket.com/prices-history` | `prediction_markets.py:434` | No backend caller. |
| LLM via the injected `llm_call(prompt) -> str` | `prediction_markets.py:780, 844` | Provider-agnostic. ReportAgent wraps `self.llm.chat(temperature=0.0)` with a "strict classifier" system prompt (`report_agent.py:2636-2646`). |
| Subprocess `sys.executable backend/scripts/resolution_monitor.py run --all-recent` | `resolution_autorun.py:43-48` | 900 s timeout, `cwd=backend/scripts`, output captured. |
| `fcntl.flock(LOCK_EX)` | `forecast_ledger.py:363-364` | Advisory lock on `resolutions.jsonl`. |
| Filesystem: append and read of ledger JSONL; tail and full reads of progress logs | see Data & artifacts | `ensemble.py`, `backtest.py` and `requirement_spec.py` do no I/O. |

---

## Cross-module edges

**Callers into this slice** (non-test, found by grep):

- `forecast_ledger`:
  - `report_agent.py:3183` (`calibration_summary`), `:3200` (`append_forecast`)
  - `backend/scripts/resolution_monitor.py:44, 560, 573-574, 696-697`
  - `backend/scripts/golden_eval.py:377, 446-458`
  - **No callers** for `due_for_resolution`, `recalibration_param`, `evaluation_ledger_dir` (used internally only) or `read_market_resolutions` (used internally only).
- `ensemble`:
  - `pipeline_orchestrator.py:8717` (`aggregate_forecasts`), `forecast_extractor.py:2820` (`pool_binary_forecasts`)
  - `forecast_extractor.py:3049, 3278, 3738` (`_norm_name`), `backtest.py:18`
  - `backend/scripts/forecast_tools.py:27`, `batch_runs.py:62, 650`, `model_comparison.py:52`, `scheduled_rerun.py:70`
  - `drf2/driver/ensemble.py:19-25`, which imports the private `_ensemble_agreement, _extremized_logodds, _mean, _norm_name, _stdev`
- `backtest`:
  - `forecast_ledger.py:255, 306`, `backend/app/api/sdk.py:50, 331`
  - `forecast_tools.py:28, 54-55`, `golden_eval.py:447`
  - `apply_recalibration` has no production caller.
- `resolution_autorun`: `backend/run.py:41-42` (`start`), `backend/app/api/research.py:349-352` (`trigger_once`).
- `requirement_spec`: `report_agent.py:1599, 1737, 3059, 6094, 8728, 8781`.
- `research_progress`:
  - `pipeline_orchestrator.py:61-63, 2477, 11147`
  - `backend/app/api/research.py:32-35, 895-900, 918`
  - `backend/scripts/export_demo_site_data.py:48, 125`
- `prediction_markets`:
  - `report_agent.py:2611-2663` (`PolymarketClient`, `derive_market_queries_llm`, `score_market_relevance`, `snapshot_for_queries`), `:2706-2712` (`requote_markets`), `:2747` (`render_markets_block`)
  - `backend/scripts/resolution_monitor.py:508` (`PolymarketClient` → `requote_markets`, `fetch_resolutions`)

**Calls out from this slice:**
- `config.Config` from every module, lazily or with a guard.
- `utils.sim_timeline._TIER4` and `extract_horizon` (`forecast_ledger.py:201-206`).
- `forecast_extractor._binary_key` (`ensemble.py:281`).
- `utils.logger.get_logger` (`resolution_autorun.py:24`).
- `httpx` (`prediction_markets.py:31`).
- `backend/scripts/resolution_monitor.py`, run as a subprocess.

**Parallel copies, not callers:** the research-stage market fetch lives in `deerflow_bridge/deerflow_research.py:14496-15720`, `deerflow_bridge/market_tools.py:37, 231` and `drf2/config/market_tools.py:27, 141`. These are hand-maintained mirrors of this module's normalisation and retry rules.

---

## Invariants, gates, validation

- **Production calibration excludes evaluation rows by record type.** `is_production_calibration_row` is applied in `calibration_summary` and `recalibration_param` unless `include_evaluation=True` (`forecast_ledger.py:49-63, 250, 295`). Golden writes aimed at the production dir are redirected (`:175-178`).
- **`resolutions.jsonl` uniqueness.** Each (report_id, forecast_id, market_id) is recorded at most once. The first write wins and is never overwritten, enforced under a thread lock plus flock (`:405-417`).
- **Ledger readers tolerate corrupt lines.** Bad JSON lines are skipped (`:224-227, 339-342`).
- **Ensemble.**
  - Within one run, scenarios never merge through the semantic path (`ensemble.py:90-91`). Exact-name hits are not guarded (see Surprises).
  - Published probabilities are renormalised to sum to about 1 (`:236-238`).
  - `agreement` is None rather than 0 when alignment cannot establish consensus (`:386-388`).
- **Progress.**
  - Monotonic, never decreases, capped at 99 (`research_progress.py:182-196, 367`).
  - Only lifecycle-kind lines cross phase boundaries (`:233-235`). Activity always keeps one point in reserve below the band ceiling (`:366`).
  - The parallel aggregate never decreases thanks to `previous` and is capped at 95 (`:391-392`).
  - The full snapshot either returns everything or raises; it is never silently truncated (`:540-555`). Symlinked logs and dirs are rejected (`:397, 424, 444-445, 453, 464`).
- **Market anchors.** A market qualifies only if it is not closed, its Yes price lies in (0,1), and its volume is ≥ `min_volume` (`prediction_markets.py:515-524`). A resolution requires `closed` and some outcome priced ≥ 0.99 (`:175`).
- **Re-quote never drops rows**, and failures are marked explicitly with `requote_failed` (`:366-387`).
- **Report fallback fetch is fail-closed.** Only LLM-scored rows survive (`report_agent.py:2663`).
- **The binary minimum can only rise from the Config floor** (`report_agent.py:8733-8734`).
- **Autorun.** At most one run is in flight per process (`resolution_autorun.py:66-69`). The 900 s timeout bounds a hung subprocess.

---

## Failure modes & recovery

| Failure | Behaviour | Anchor |
|---|---|---|
| Ledger dir not writable | `append_*` returns None; ReportAgent also wraps calls in try/except and continues. | `forecast_ledger.py:109-110, 184-185, 419-420`; `report_agent.py:3191, 3204` |
| Torn or corrupt JSONL line | Skipped on read. | `forecast_ledger.py:224-227` |
| `calibration_report` raises | `calibration_summary` returns Nones with a count. | `forecast_ledger.py:260-261` |
| `flock` unsupported | Falls back to in-process mutual exclusion only. | `forecast_ledger.py:365-366` |
| Gamma or CLOB network failure | One jittered retry on transient errors, then None, then an empty result. Diagnostics go to `last_error` and `transport_errors`. | `prediction_markets.py:237-269` |
| LLM query or score parse failure | Falls back to the heuristic queries, or to volume order. | `prediction_markets.py:797-806, 857-858, 882-884` |
| Monitor script missing, crashes or hangs | Logged; returns `{ok: False}`; the in-flight flag is always cleared in `finally`. | `resolution_autorun.py:41-58, 75-77` |
| Full progress snapshot too large | `ResearchProgressLimitError` → HTTP 413. | `research_progress.py:434-459, 540-544`; `research.py:918-919` |
| Log file changes during the full snapshot | `RuntimeError` → HTTP 500. | `research_progress.py:546-555`; `research.py:920-921` |
| Seed ensemble produces fewer than 2 forecasts | No `ensemble_forecast.json` is written. | `pipeline_orchestrator.py:8712-8716` |
| Alignment finds fewer than 2 consensus buckets | `agreement` is None → confidence "medium". | `ensemble.py:386-388`; `pipeline_orchestrator.py:8491-8494` |

---

## Surprises

1. **The calibration loop is open (suspected; high impact).** Nothing in production sets `resolved: True` or `outcome` on a `ledger.jsonl` row:
   - `append_forecast` always writes `resolved: False` (`forecast_ledger.py:97`).
   - `/api/v1/resolve` writes `resolved.json` in the report folder instead (`sdk.py:228-230, 344`).
   - `forecast_tools backtest` reads a user-supplied file (`forecast_tools.py:49-55`).
   - The "atomic rewrite for resolution" in the docstring (`forecast_ledger.py:10`) does not exist.

   As a result, production `calibration_summary()` always returns `n_resolved = 0`, and ReportAgent never adds `historical_calibration` (`report_agent.py:3184-3190`). Market resolutions go to `resolutions.jsonl`, which only `market_brier_summary` reads and which never feeds `confidence_rationale`. `ARCHITECTURE_MAP.md:1021` and `DRF_ARCHITECTURE.md:1378-1379, 1386-1387` describe the loop as closed.
2. **Dead or orphan code:**
   - `due_for_resolution` (`forecast_ledger.py:264`). The docstring says `scheduled_rerun.py` uses it (`:11-12`); that script only imports `_norm_name` (`scheduled_rerun.py:70`).
   - `recalibration_param` (`:277`) and `apply_recalibration` (`backtest.py:230`) are used only by tests.
   - `PolymarketClient.fetch_price_history` (`prediction_markets.py:420`) has no backend caller; the bridge mirror is used.
   - `_RESOLVED_PRICE_LO` (`:57`) is never referenced.
3. **Knobs that cannot be configured.** `CAL_MIN_RESOLVED` (`backtest.py:174`), `REPORT_RECALIBRATE_FROM_LEDGER` (`forecast_ledger.py:300`) and `PREDICTION_MARKETS_REQUOTE_CHUNK` (`prediction_markets.py:398`) are read with `getattr(Config, …)` but are not defined in `config.py`, and nothing calls `setattr(Config, …)`. They are effectively hardcoded to 0, False and 20. `DRF_ARCHITECTURE.md:1369, 1684` presents them as live knobs.
4. **Default ensemble pooling is not the arithmetic mean.** The comment at `ensemble.py:204-205` says an unset `ENSEMBLE_EXTREMIZE_A` falls back to the arithmetic mean, but Config always sets it (default 1.0, `config.py:333`). So `pooling == "extremized_logodds"`, geometric odds pooling with a = 1, is the default for both seed and multi-model pooling. Separately, the arithmetic `mean_probability` ignores runs that did not surface a scenario (it does not count them as zero).
5. **Doc-vs-code drift in `DRF_ARCHITECTURE.md`:**
   - `N_FORECAST_SEEDS` default 3 (`:1354`) vs 1 in code (`config.py:303`).
   - `ENSEMBLE_EXTREMIZE_A=2.0` (`:1360`) vs 1.0 (`config.py:333`).
   - "failed tracks stay in the denominator" (`:330-331`, repeated at `:1759`) vs code that excludes failed tracks (`research_progress.py:383-388`; `pipeline_orchestrator.py:11151, 11260`).
   - Golden rows go "into the same ledger" (`:1380-1381`) vs redirected to `_evaluation_ledger` (`forecast_ledger.py:175-178`).
   - The ledger "plus `objective_signals`" (`:1375-1376`) vs ReportAgent never passing `objective_signals` (`report_agent.py:3200-3203`).
   - Stale line anchors throughout: `research_progress :42-206 / :209-230 / :256-314` vs actual `:147-368 / :371-392 / :500-517`; `append_forecast :37` vs `:66`; `calibration_summary :179` vs `:233`; `append_market_resolution :288` vs `:369`.
6. **"Polymarket/Kalshi/Oddpool".** Only Polymarket is implemented. "Oddpool" survives only as the legacy env alias `ODDPOOL_MAX_MARKETS` (`config.py:1424-1426`; bridge `deerflow_research.py:15257`). There is no Kalshi code in `backend/app`, `backend/scripts`, `deerflow_bridge` or `drf2`.
7. **Four copies of the Polymarket logic:** `backend/app/utils/prediction_markets.py`, `deerflow_bridge/market_tools.py` (`:37, 149, 231`), `drf2/config/market_tools.py` (`:27, 83, 141`) and inline in `deerflow_bridge/deerflow_research.py` (`:14507-15720`, with its own `_pm_normalize_market`, `_pm_cap_per_event`, `derive_market_queries_llm`, `score_market_relevance`). The research artifact `prediction_markets.json` comes from the bridge copy, so changing this module does not change research-stage behaviour.
8. **Ledger duplication (suspected).** `append_forecast` has no deduplication and no lock. Every `generate_report` appends, including each extra ensemble seed (`pipeline_orchestrator.py:8762`, `:8888` → `report_agent.py:11502` → `:3200`) and any regeneration of the same report. Unpublishable reports are appended too: there is no publish-gate check at `report_agent.py:3197`, whereas `/api/v1/resolve` does gate (`sdk.py:302-308`). Correlated seed rows would over-weight one question if the ledger were ever resolved.
9. **The same-run guard is bypassable (suspected).** `align_scenario_buckets` guards only the semantic path. If a run contains two scenarios whose names hit the same `by_name` entry (duplicates, or an alias registered by an earlier semantic merge), both land in one bucket (`ensemble.py:84, 114`). `support = len(probs)` can then exceed `n_runs`, and `support_ratio` can exceed 1 (`:223-224`).
10. **`ENSEMBLE_ALIGN_MIN_OVERLAP=0` is coerced to 0.34** by `or 0.34` (`ensemble.py:70`). Similarly, `PREDICTION_MARKETS_PER_QUERY=0` becomes 15 (`prediction_markets.py:310`).
11. **Language sniff picks up research-report text (suspected).** `detect_output_language` is given the research report and the situation brief as well as the brief (`report_agent.py:1600-1601`). Any phrase "in English" in those texts, such as "sources published in English", forces English through `\b(in|用)\s*english\b` (`requirement_spec.py:20`). English directives also outrank an explicit `用中文` in the brief, because they are checked first (`:42-44`).
12. **Binary-count regex has no left boundary (suspected).** `(\d{1,2})\s*\+?\s*binary` (`requirement_spec.py:53`) turns "…by 2030 binary outcomes" into 30. That raises the binary minimum to 30, because ReportAgent takes the max (`report_agent.py:8733-8734`).
13. **Lenient Brier for an unmatched outcome.** `score_forecast` still scores an outcome that matches no scenario, as Σ p_i² (`backtest.py:56-61`), and `calibration_report` includes it in `mean_brier` (`:92-94`). A typo in the outcome can score better than a wrong-but-matched outcome. `mean_brier` (a per-forecast multi-class sum) and `brier_pooled` (per prediction) are different scales in the same payload (`:170, 179`).
14. **Autorun cosmetics and the reloader (suspected).** The log always says "首轮延迟 60s" ("first run delayed 60s") (`resolution_autorun.py:116`). `run.py` calls `start_resolution_autorun()` before `app.run(debug=Config.DEBUG)` (`run.py:41-42, 57`). With `FLASK_DEBUG=true` the Werkzeug reloader runs that code in both the parent and the child, so two schedulers could start. The process-local in-flight flag would not dedupe across them; only the `resolutions.jsonl` flock protects ledger idempotency.
15. **Progress-estimator corner cases.**
    - v3 gap rounds ≥ 3 reuse the round-2 slot 64–68 (`research_progress.py:131-133`), so `_advance_phase` does not open a new band and the unit ledger is not re-armed; progress plateaus at 67.
    - The `[tool]`/`[result]` activity check is a raw substring test (`:358`).
    - Tail mode deduplicates identical lines within one source (`:479-481`), so repeated continuation lines without timestamps collapse in the live console. Full mode keeps them.
    - Timestamps are sorted as strings (`:496`), so mixed offset formats (Z vs +00:00) could misorder rows.
16. **`_request`'s string error-class branch** (`prediction_markets.py:262`) is effectively unreachable. A transient status on attempt 2 goes through `raise_for_status`, so `last_err` is an `HTTPStatusError` instance, not a string.
17. **`append_market_resolution` re-reads the whole `resolutions.jsonl`** under the lock on every append (`forecast_ledger.py:410-413`), so cost grows with history (O(n) per append).
18. **`market_brier_summary.n_resolved`** counts records with `brier_contribution = None` (that is, missing `model_p`), while `mean_brier` averages only the numeric ones (`forecast_ledger.py:431-436`).
