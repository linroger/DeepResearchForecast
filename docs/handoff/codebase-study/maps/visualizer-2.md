# visualizer-2 — report_visualizer.py part 2

Slice: `backend/app/services/report_visualizer.py` lines 2742-5411 (end of file). Every line of
the slice was read. Helpers outside the slice were read only to explain what the slice calls. All
paths in this document are relative to the repo root. Unless a line says otherwise, a bare
`:NNNN` anchor means `backend/app/services/report_visualizer.py:NNNN`.

## Purpose & position in the pipeline

This slice holds the main chart family of the deterministic report visualizer. No LLM is involved.
It has five parts:

1. **Plotly I/O plumbing** (:2742-2913). This covers the feature gates, the shared
   `plotly.min.js` bundle, the HTML writer and its load guard, the kaleido PNG export (one-shot or
   batched, with a process-wide circuit breaker), the markdown tables written when a chart is too
   sparse, and `_save_pair`, which saves the HTML and its PNG together.
2. **Sixteen Plotly chart builders** (:2915-4309). Each one renders `charts/<stem>.html` and queues
   or exports `charts/<stem>.png`.
3. **The `build_all` orchestration entry** (:4313-4545). It runs the builders, records why each
   skipped builder did not run, flushes the queued PNGs, runs the matplotlib fallback family
   (`_run_matplotlib_family`, :4547-4660) and writes `viz_manifest.json` with a provenance block.
4. **Persistence helpers** (:4664-4777). These are the Mermaid writer (dead code), the manifest
   writer, the provenance hasher and the price-history loader.
5. **Module-level pure helpers** (:4784-5411). These cover causal-string parsing, coalition
   normalization, `_first_float`, price-anchor normalization, scenario-row extraction and interval
   provenance, flexible date parsing, the timeline lane taxonomy, actor-name canonicalization and
   the network layout.

Position: this is Stage 6 (Report). `ReportAgent._inject_visualizations`
(`backend/app/services/report_agent.py:8882`) calls `ReportVisualizer().build_all(...)` at
`report_agent.py:8906` during report finalization. The call comes after the Part-1 binary table is
prepended and before the three-part skeleton is built (`report_agent.py:11513-11521`). The
offline `backend/scripts/backfill_report_visuals.py:503` calls it as well. The outputs are
`reports/<id>/charts/*` and `reports/<id>/viz_manifest.json`. The report markdown embeds them
(`report_agent._render_viz_block`, `report_agent.py:9106`). The API serves them
(`backend/app/api/report.py:1279`, `:1358`), and the pipeline integrity checks verify them
(`backend/app/services/pipeline_orchestrator.py:9560`, `:9631`).

## Walkthrough (source order)

### (C) Plotly I/O plumbing

**`_interactive_ok(self)`** (:2742-2744)
- Returns `PLOTLY_AVAILABLE and bool(_cfg("REPORT_VIZ_INTERACTIVE", True))`.
- `PLOTLY_AVAILABLE` is set by a module-level import probe of `plotly.graph_objects` (:156-161).
- Every Plotly builder checks this first and returns `None` (or `[]`) when it is False.

**`_png_export_ok(self)`** (:2746-2749)
- Returns `KALEIDO_AVAILABLE and _KALEIDO_RUNTIME_OK and bool(_cfg("REPORT_VIZ_PNG_EXPORT", True))`.
- `KALEIDO_AVAILABLE` only checks `importlib.util.find_spec("kaleido")` (:180-184). It does not
  check that Chrome or Chromium is present.
- `_KALEIDO_RUNTIME_OK` is a module global, initially `True` (:186), that is tripped once and
  never reset.

**`_PLOTLY_BUNDLE_NAME = "plotly.min.js"`** (:2751)

**`_ensure_plotly_bundle(self, charts_dir)`** (:2753-2771)
- If `charts_dir/plotly.min.js` already exists (`os.path.isfile`, :2760), it returns True. It
  does not check the file's version.
- Otherwise it writes `plotly.offline.get_plotlyjs()` (about 4.9MB) to
  `plotly.min.js.<pid>.tmp`, then calls `os.replace` (:2764-2767).
- Any exception: logs at debug level and returns False, so the caller falls back to inline mode
  (:2769-2771).

**`_inject_plotly_load_guard(html)`** (staticmethod, :2773-2791)
- Inserts an inline `<script>`. On `DOMContentLoaded`, if `window.Plotly` is missing, the script
  prepends a red notice div: "Interactive chart could not load the shared plotly.min.js ...".
- The script is inserted before the first `</body>`, or appended to the end if there is none.
- It is used only in directory mode.

**`_save_html(self, fig, charts_dir, filename)`** (:2793-2821)
- Creates `charts_dir` if needed.
- `force_inline = bool(_cfg("REPORT_VIZ_PLOTLYJS_INLINE", False))` (:2806).
- `include` is `"inline"` if `force_inline` is set or the bundle could not be written; otherwise it
  is `"directory"` (:2807-2808).
- Calls `fig.to_html(include_plotlyjs=include, full_html=True, config={"displayModeBar": True, "responsive": True})`.
- Calls `_finalize_plotly_html(html, _plotly_document_title(fig, filename))` (:2811). That helper
  (:127-135) injects `<title>` and an embedded SVG favicon. `_plotly_document_title` (:116-124)
  strips tags from `fig.layout.title.text`, falling back to the filename in title case.
- Adds the load guard in directory mode (:2812-2813).
- Writes atomically: `out_path + ".tmp"`, then `os.replace` (:2814-2817).
- Returns `os.path.join("charts", filename)`, a path relative to `report_dir`. Any exception
  returns `None` and is logged at debug level (:2819-2821).

**`_save_png(self, fig, path)`** (:2823-2842)
- Returns False if `_png_export_ok()` is False.
- Calls `fig.write_image(path, scale=2, width=1200, height=<fig.layout.height or None>)` (:2836),
  then returns `os.path.exists(path)`.
- **On any exception** it sets the module global `_KALEIDO_RUNTIME_OK = False` and
  `self._kaleido_failed = True`, logs a WARNING and returns False (:2838-2842). After that, no
  report in this process gets kaleido PNGs.

**`_queue_png(self, fig, charts_dir, stem, item_id)`** (:2844-2854)
- Does nothing if PNG export is off.
- The PNG goes to `charts/<stem>.png` (both the absolute and relative paths are built).
- In `self._batch_mode`, which `build_all` sets, it appends `(fig, abs, rel, item_id)` to
  `self._png_jobs`.
- Otherwise it renders immediately through `_save_png`. On success it records
  `self._png_done[item_id] = rel`.

**`_flush_png_jobs(self)`** (:2856-2885)
- Swaps out `self._png_jobs`. It returns if the list is empty or export is off (:2860-2862).
- **Batch path:** `plotly.io.write_images(figs, paths, scale=2, width=1200, height=heights)`, with
  each height taken from `fig.layout.height` or a default of 600 (:2864-2873). Every job whose file
  now exists goes into `_png_done` (:2874-2876).
- If anything raises (for example, older plotly without `write_images`, or kaleido below v1), it
  logs at INFO and falls back to `_save_png` one job at a time. That loop stops when the breaker
  trips (:2881-2885).
- `global _KALEIDO_RUNTIME_OK` is declared (:2859), but the batch path never assigns it. A failed
  batch therefore does not trip the breaker; only a per-image failure does.

**`_write_density_fallback(self, item_id, stem, lines, charts_dir)`** (:2887-2904)
- Writes `charts/<stem>_table.md` atomically from `lines`.
- Records `self._skip_notes[item_id] = {"reason": "below_density_threshold", "fallback_path": "charts/<stem>_table.md"}`.
- If the write fails, `fallback_path` is left out but the reason is still recorded (:2902-2904).

**`_save_pair(self, fig, charts_dir, stem, item_id=None)`** (:2906-2913)
- Calls `_save_html(fig, charts_dir, f"{stem}.html")`. If that succeeds, it calls
  `_queue_png(..., item_id or stem)`.
- Returns the HTML relative path only. The PNG path is looked up later in `_png_done`.

### (C) Plotly builders, reused data contract

All builders share the same contract:
- They return `None` (or `[]`) when `_interactive_ok()` is False.
- The whole body is wrapped in `try/except Exception`, which logs at debug level and returns
  `None`, so they never raise.
- They style through `_apply_layout` (:304-318): font stack `_VIZ_FONT`, `_PALETTE`, surface
  `#fcfcfb`, title at x=0.02 with font size 16, and default margins l10/r24/t58/b46.
- Text goes through `_html_text` (:607), which truncates and rewrites a pair of `$` as `&#36;` so
  MathJax does not trigger. `_wrap_hover` (:321) and `_wrap_label` (:623) wrap long text with
  `<br>`.

**`build_scenario_bars_html(forecast, charts_dir, ensemble=None)`** (C1, :2915-3010)
- Rows come from `_extract_scenario_rows(forecast, ensemble)` (:2925). No rows means `None`.
- Draws one horizontal `go.Bar` (colour `_COLOR_MODEL`) with hover text: name, `P`, the
  interval label and lo–hi (only when `hi > lo`), `ensemble stdev` and `support ratio`
  (:2930-2946).
- Adds a percentage annotation per row, placed just past the interval's upper end (or past `p` if
  there is no interval), at `min(edge + 0.015*x_max, x_max)` (:2948-2958).
- For each interval source, in the order of `_SCENARIO_INTERVAL_ORDER`
  ("ensemble", "declared", "self_consistency", :4969), adds a `go.Scatter` marker trace with an
  asymmetric `error_x`. Each source has its own colour, symbol and cap width from
  `_SCENARIO_INTERVAL_STYLES` (:4942-4966) and a hovertemplate (:2959-2994).
- Title: `_scenario_interval_title(rows)` plus a `<sup>` subtitle from
  `_scenario_interval_subtitle(rows, forecast)` (:2996-2998).
- Height is `max(340, 42*n + 160)`. The x range is `[0, max(1, 1.2*max p)]` with format `.0%`.
  The y axis is reversed so the highest-probability scenario is on top. Top margin is 74
  (:2999-3005).
- Output stem: `scenario_probabilities` (:3006).

**`build_model_vs_market_html(forecast, charts_dir)`** (C2, :3012-3104)
- `forecast["binary_forecasts"]`, or the argument itself if it is a list (:3019).
- Uses each binary forecast that has a dict `market_anchor`, a model value (`probability` via
  `_to_float`) and a market value (`implied_yes_prob`, falling back to `implied_prob`)
  (:3026-3045).
- The label is `id`, then `statement`, then `market_id`, then `anchor.market_id`, truncated to 46
  characters. Statements are truncated to 110.
- **Density gate:** fewer than `_MODEL_VS_MARKET_MIN_ANCHORED` (3, :255) anchored rows produces a
  markdown table (proposition, model, market, Δ in pp) through `_write_density_fallback` and
  returns `None` (:3050-3067).
- Otherwise it clears any stale skip note (:3068), draws a grey line segment per row, then a
  "Market implied" marker trace (`_COLOR_MARKET`) and a "Model" marker trace (`_COLOR_MODEL`), each
  size 11 (:3069-3088).
- Title includes `<sup>N market-anchored propositions ...</sup>`. Height is `max(320, 40n+170)`
  and the x range is [0, 1] (:3089-3100).
- Output stem: `model_vs_market`.

**`build_worldstate_area_html(trajectory, charts_dir)`** (C3, :3106-3168)
- Rows come from `trajectory["trajectory"]` or a plain list. Fewer than 2 rows returns `None`.
- For each dict row with a non-empty `shares` dict:
  - `x` is `round` via `_to_float`, falling back to the **original row index** `i` (:3127-3129).
  - Share values must parse as float. Series names are kept in first-seen order.
  - `_trajectory_row_date(r)` supplies a calendar date (:3140).
- Needs at least 2 snapshots (:3141).
- Uses a calendar x axis (ISO strings, title "Date") only if **every** snapshot has a date.
  Otherwise the x axis is the round number, titled "Forecast update step" (:3143-3151).
- One `go.Scatter(stackgroup="one")` per series, with missing shares treated as 0.0. Shares are
  not normalized (:3153-3161).
- Title "Forecast Outcome-Share Trajectory", height 460. Output stem: `worldstate_trajectory`.

**`render_market_price_history_html(price_history, anchors, out_dir)`** (C4, :3170-3225)
- Needs a non-empty `price_history` dict.
- Normalizes with `_normalize_price_anchors` (:3183), then caps at
  `int(_cfg("REPORT_VIZ_MAX_NODES", 40) or 40)`, keeping the first anchors (:3186-3188).
- **One figure per anchor:**
  - A "Market implied P(yes)" line plus markers (`_COLOR_MARKET`).
  - A dashed `add_hline` at the model probability, labelled "Model P(yes) = NN%".
  - A paper-anchored annotation box: "Divergence (model − market): ±N pp".
  - Title is `a["label"]`, height 420, y range [0, 1] (:3190-3217).
- Stem `market_price_history_{gi}` with gi starting at 1. Returns the list of HTML relative
  paths (:3218-3222).

### (D) WAVE9 Plotly builders

**`build_binary_dotplot_html(forecast, charts_dir)`** (D1, :3231-3341)
- For each binary forecast with a numeric `probability`, `prob` or `p` (via `_first_float`):
  - `conf` is the `confidence` field, kept only if it is in [0, 1] (:3251-3253).
  - `market` comes from the anchor's `implied_yes_prob`/`implied_prob`.
  - The label is `"{id≤10} · {statement wrapped to 2 lines of 55 characters}"`.
  - The hover shows id, P, the wrapped statement, theme and the market value.
- Sorted by `(-p, label)` (:3274).
- **Confidence is colour-encoded only when every row has a valid confidence** (:3276). It then
  uses a `_SEQ_BLUES` colourscale with cmin 0, cmax 1 and a colorbar titled "Declared confidence"
  (:3301-3309). Otherwise a single colour is used and the subtitle says "point estimates —
  confidence not declared", plus "N market-anchored (paired diamonds)" when there are anchors
  (:3316-3325).
- Anchored rows get a grey connector and red diamond markers. There is a dotted vline at 0.5.
- Row height is 44 if any label wraps, else 30. Height is `max(340, rh*n + 170)`. The y axis uses
  `categoryarray=labels`, reversed.
- `p` is **not** range-checked, while the x axis is fixed to [0, 1].
- Output stem: `binary_forecast_dotplot`.

**`build_timeline_lanes_html(timeline, charts_dir)`** (D2, :3343-3464)
- Rows come from `timeline["timeline"]` or a list, then `_prepare_timeline_events` (:3354), which
  parses, deduplicates, caps and sorts them.
- Lanes are the `_TL_CATEGORIES` names plus "Other". Only lanes that are used are shown, in
  taxonomy order (:3357-3360).
- `_timeline_label_plan(events, lane_idx, max_labels=10)` (helper at :496) chooses up to 10
  salient events that get two-digit index numbers. The plan's collision geometry is estimated in
  matplotlib units.
- One trace per lane:
  - Markers are size 19 when the event is numbered (with white size-7 index text) and 9 otherwise.
  - Vertical jitter cycles through `(-0.40, -0.20, 0, 0.20, 0.40)` by position within the lane.
  - Hover shows the full date and the wrapped event text (:3364-3387).
- **Key-events block** below the plot:
  - Labels are wrapped to 2 lines of 55 characters.
  - Two columns when there are more than 5 keys.
  - Row offsets start at 48 and add 25 per line (41 when a row holds a wrapped label).
  - A "+N more event(s) shown as unlabeled dots" note is added when some events have no number.
  - The bottom margin equals the key height, and annotations are placed in paper coordinates
    scaled by `paper_height` (:3388-3460).
- The "Date" x title is suppressed when the key is present (:3420).
- The y axis uses an explicit reversed range `[max+0.7, -0.7]` with zeroline off. The legend is
  hidden.
- Height is `max(390, 82*lanes + 155) + key_height`. Output stem: `timeline_lanes`.

**`build_actor_network_html(actors, charts_dir, graph_priors=None)`** (D3, :3466-3622)
- Relations come from `actors.relationships`, `actors.relations` or `actors.edges`, or `actors`
  itself if it is a list.
- `canon = _canonical_actor_map(actors.actors)` (:3480).
- `graph_priors` are numeric and keyed by `_norm_key`.
- Edge collection:
  - Endpoints come from `source`/`from` and `target`/`to`, canonicalized with `_canonicalize`.
  - Self-loops are dropped.
  - `typ` is `type`, `relation`, `rel` or `"REL"`, upper-cased.
  - Edges are deduplicated on `(src, tgt, typ)`. The sign is `_sign_of(r)` or "±".
  - Degree and first-seen order are tracked (:3488-3509).
- Node cap: `REPORT_VIZ_NETWORK_MAX_NODES` (default 60). Nodes are ranked by prior, then degree,
  then first-seen. The kept set is `ranked[:max(2, cap)]`, and edges are filtered to that set
  (:3513-3522).
- Layout comes from `_network_layout` (:3523).
- Draws three edge traces, one per sign (`+` green, `−` red, `±` grey), each a polyline separated
  by `None`, with opacity 0.55 (:3531-3550).
- Node traces are one per `role_class` (from the actors metadata, default "other"):
  - Size is `10 + 26*w/wmax`. `w` is the prior if any kept node has a prior; otherwise it is the
    degree.
  - Hover shows the name, role_class, influence, degree and graph prior (:3552-3588).
- Labels come from `_actor_label_plan(..., max_labels=16)` and are drawn as arrow annotations
  (:3589-3599).
- Axes are hidden, ranges are padded by 6% (x) and 8% (y) of span, `scaleanchor` is x, and height
  is 780.
- Output stem: `actor_network`.

**`build_actor_bubble_html(actors, charts_dir)`** (D4, :3624-3706)
- `x` is salience. If salience is a dict, use `score`, else `_LEVEL_NUM[tier]/4`. If it is a
  scalar, use its float value, else `_LEVEL_NUM[str]/4`. The default is 0.5. The value is clamped
  to [0, 1].
- `y` is `_LEVEL_NUM[influence]` (default 2.0) plus a deterministic jitter of `((i%5)-2)*0.09`.
- Size is relationship degree. Colour is by `role_class`.
- The x range is [-0.05, 1.1]. The y ticks run 1-4, Low to Very high, over the range [0.4, 4.6].
- Output stem: `actor_influence_salience`.
- **Never called by `build_all`**, which always skips it (:4430-4433).

**`build_source_sunburst_html(sources, charts_dir)`** (D5, :3708-3773)
- Counts sources by `(tier|"untiered", source_origin|"unknown", reachable→reachable/unreachable/unchecked)`.
- Builds a three-level `go.Sunburst` with `branchvalues="total"`:
  - The tier level is ordered by `_TIER_RANK` and coloured with `_TIER_COLOR`.
  - The tier/origin level uses its tier's colour.
  - The reach level is green, red or grey.
- Title includes `n=`. Height 560. Output stem: `source_mix_sunburst`.
- Opt-in only, through `REPORT_META_CHARTS`.

**`_metric_point_hover(point, unit)`** (staticmethod, :3775-3790)
- Hover text for one point: the representative row's metric, then
  `display_value unit @ x_label · forecast|actual`, plus `n=` when n > 1, plus "⚠ stale" when
  stale. Definition and source lines are added when present.

**`build_metric_trajectories_html(quantitative, charts_dir)`** (D5b, :3792-3878)
- Panels come from `_metric_trajectory_panels(quantitative)` (helper at :1489, up to 8 families).
  That helper uses the DRF2 `metric_family` path if any row has one, else the legacy folded-name
  path.
- Uses `make_subplots(rows=n, cols=1, vertical_spacing=min(0.12, 0.8/n))`.
- Within a panel, numeric integer years are plotted on a numeric axis (`tickformat="d"`, with
  `dtick=1` if the span is at most 12 years). Otherwise the axis is categorical with
  `categoryorder="category ascending"` (:3819-3821, :3854-3862).
- Colour is `_PALETTE[li]` if the panel is split or any panel has more than one line; otherwise it
  is `_COLOR_MODEL`.
- Forecast points use diamond markers and actual points use circles. Stale points get a red marker
  outline. A line with a single point draws markers only.
- Legend entries are deduplicated across panels with `legendgroup`. When there are multiple
  lines, the legend moves to the bottom (`y=-0.04`, `margin.b=96`).
- Height is `max(420, 240n + 140)`. Output stem: `metric_trajectories`.

**`build_technology_shares_html(quantitative, charts_dir)`** (D5c, :3880-3925)
- Uses `_prepare_technology_shares` (:1502), which takes each family's latest year that has at
  least 2 technologies.
- One bar subplot per family, with the share % as outside text and hover showing value, share,
  `n` and source.
- Height is `max(420, 260n + 120)`. Output stem: `technology_shares`.

**`build_regional_comparison_html(quantitative, charts_dir)`** (D5d, :3927-3974)
- Uses `_prepare_regional_comparison` (:1566), which needs at least 2 regions in the latest year.
- Bars are coloured `_PALETTE[2]` for forecasts and `_COLOR_MODEL` for actuals. Outside text
  shows `display_value`.
- Output stem: `regional_comparison`.

**`build_quantitative_dots_html(quantitative, charts_dir)`** (D6, :3976-4089)
- Uses `_prepare_quantitative_panels` (:1055, at most 3 panels of 10 rows, each with one strict
  denominator).
- **Density gate:** a panel is dense if it has at least 4 rows or at least 2 distinct metrics
  (`_quant_panel_is_dense`, :260).
- If no panel is dense, it writes a markdown table of all rows (metric, value, unit, as of, tier,
  status, source) to `charts/quantitative_claims_table.md` and returns `None` (:3994-4023).
- If some panels are dense, **only the dense panels are drawn**. The sparse ones are dropped
  without being tabled (:4025).
- Subtitles come from `_quant_panel_subtitles` (:268), which keeps them distinct.
- `row_heights` are proportional to row count (minimum 2), with `vertical_spacing` 0.16.
- Each panel has an observed trace (circles) and a projection trace (diamonds). Stale rows get a
  red outline and a "⚠" suffix. The y axes are reversed. The legend is horizontal at the top.
- Height is `max(560, 32*rows + 145*panels + 160)`. Output stem: `quantitative_claims`.

**`build_forecast_revisions_html(quantitative, charts_dir)`** (:4091-4143)
- Uses `_prepare_forecast_revision_series` (:1634), with at most 3 series and at least 3
  corroborated vintages each.
- One subplot per series: line plus markers plus value text. Stale points are coloured red. The
  x axis is "Forecast vintage" with `dtick=1`.
- Subplot titles are **not** passed through `_html_text` (:4103).
- Height is `max(400, 300n + 100)`. Output stem: `forecast_revisions`.

**`build_driver_tornado_html(ensemble, charts_dir, graph_priors=None)`** (D7, :4145-4228)
- Iterates over the ensemble scenarios. Each scenario's weight is `mean_probability`, then
  `probability`, then `support_ratio`, else `1/n`.
- Each `key_drivers` string is merged into an existing canonical driver if the token Jaccard is at
  least 0.6 (`_tokens`/`_jaccard`, :346-356). Its weight is accumulated and the scenario name is
  recorded (:4158-4184).
- Prior boost:
  - Graph-prior entity names must be at least 3 characters.
  - The entity name must appear as a case-folded substring of the driver text.
  - The boost is the maximum matching prior value, and `score = weight*(1+boost)` (:4187-4202).
- The top 15 by `(-score, text)` are drawn as horizontal bars.
- Output stem: `driver_tornado`.
- **Always skipped by `build_all`** (:4475-4478).

**`build_contested_dumbbell_html(contested, charts_dir)`** (D8, :4230-4309)
- For each claim with at least 2 positions, only the first two positions are used.
- Weight is `max(0.5, n_sources) * _TIER_WEIGHT[tier]`. The tier defaults to S3, and
  `_TIER_WEIGHT` is S1 3, S2 2, S3 1, S4 0.5 (:301). A position whose `sources` is not a list
  counts n as 1.
- The top 12 by total weight are drawn as a dumbbell: Position A in `_COLOR_MODEL`, Position B in
  `#eb6834`.
- Output stem: `contested_claims`.
- **Always skipped by `build_all`** (:4483-4486).

### Orchestration

**`build_all(self, report_id, report_dir, artifacts)`** (:4313-4545). The docstring at
:4319-4341 lists the artifact keys.

1. If `REPORT_VISUALIZER` is false, it returns `[]` and **writes nothing**, not even the manifest
   (:4344-4345).
2. `charts_dir` is `report_dir/charts`. Batch state is reset: `_png_jobs=[]`, `_png_done={}`,
   `_batch_mode=True`, `_kaleido_failed=False`, `_skip_notes={}` (:4350-4354). The module global
   `_KALEIDO_RUNTIME_OK` is **not** reset.
3. `graph_priors` falls back to `graph_priors_structural` when it is not a non-empty dict
   (:4359-4361). `plotly_on = _interactive_ok()` (:4362).
4. The inner `_attempt(item_id, source, title, hint, data_ok, fn)` (:4364-4390) works like this:
   - Plotly off: records skip reason `plotly_unavailable_or_disabled`.
   - No data: records `no_input`.
   - Exception: records `exception:<Type>`.
   - Falsy return: records the builder's skip note if one exists (`below_density_threshold` plus
     `fallback_path`), else `empty_after_parse`.
   - Success: appends `{id, path, type:"html", title, caption: title, source, placement_hint}`.
5. Builders run in this order, which is also the manifest item order:

| # | item id | source | placement_hint | data gate | anchor |
|---|---|---|---|---|---|
| 1 | scenario_probabilities | forecast | scenarios | `_scenario_data_present` | :4394-4399 |
| 2 | binary_forecast_dotplot | forecast | binary_forecasts | non-empty `forecast.binary_forecasts` list | :4400-4404 |
| 3 | model_vs_market | forecast | binary_forecasts | same | :4405-4408 |
| 4 | timeline_lanes | timeline | timeline | `bool(timeline)` | :4409-4412 |
| 5 | actor_network | actors | actors | opt-in through `_meta_charts_on()`, else skip `methodology_not_reader_facing` | :4417-4426 |
| 6 | actor_influence_salience | always skipped: `internal_proxy_not_reader_facing` | | | :4430-4433 |
| 7 | source_mix_sunburst | sources | sources | opt-in, else `methodology_not_reader_facing` | :4438-4447 |
| 8 | metric_trajectories | quantitative | quantitative | non-empty list | :4450-4453 |
| 9 | technology_shares | quantitative | quantitative | same | :4456-4459 |
| 10 | regional_comparison | quantitative | quantitative | same | :4460-4463 |
| 11 | quantitative_claims | quantitative | quantitative | same | :4464-4467 |
| 12 | forecast_revisions | quantitative | forecast_revisions | same | :4468-4471 |
| 13 | driver_tornado | always skipped: `proxy_not_sensitivity_analysis` | | | :4475-4478 |
| 14 | contested_claims | always skipped: `proxy_evidence_weight_not_reader_facing` | | | :4483-4486 |
| 15 | worldstate_trajectory | world_state_trajectory | scenarios | `bool(wst)` | :4487-4491 |
| 16 | market_price_history_N (one item per anchor) | market_price_history | binary_forecasts | see below | :4494-4520 |

6. Market price history (:4494-4520):
   - If `_price_hist_ok()` is false: skip reason `disabled`.
   - Otherwise it loads `_load_price_history` and uses `forecast.binary_forecasts` as anchors. If
     either is missing: `no_input`. If Plotly is off: `plotly_unavailable_or_disabled`. If no
     charts come back: `empty_after_parse`.
   - Each returned path becomes an item whose id is the file stem, titled "Market-Implied P(yes)
     History vs Model".
7. `finally: self._batch_mode = False` (:4521-4522).
8. `_flush_png_jobs()`. Then each item whose id is in `_png_done` gets `png_path` when that file
   exists (:4525-4529).
9. `_run_matplotlib_family(...)` (:4534-4535).
10. `_persist_manifest(report_dir, items, skipped, provenance=_manifest_provenance(artifacts))`
    (:4538-4539).
11. An INFO log lists the item count, the png_pair count and every skip as `builder=reason`
    (:4540-4544). The function returns `items`.

**`_run_matplotlib_family(...)`** (:4547-4660)
- If `_chart_ok()` is False (matplotlib missing or `REPORT_VIZ_CHARTS` off), it records skip
  `matplotlib_family / matplotlib_unavailable_or_disabled` and returns (:4557-4560).
- `_fallback(item_id, ...)` (:4564-4582):
  - Does nothing if the Plotly item already has `png_path`.
  - Otherwise it runs the matplotlib builder. Exceptions and `None` results are dropped
    **without a skipped entry**.
  - If the Plotly item exists, the PNG is attached as its `png_path`. Otherwise a new
    `type:"png"` item is appended.
- Fallbacks run for:
  - `scenario_probabilities` → `build_scenario_bars` (:1997)
  - `model_vs_market` → `build_model_vs_market` (:2086, same at-least-3 density gate)
  - `timeline_lanes` → `build_timeline_lanes` (:2225)
  - `actor_network` → `build_actor_network` (:2357), only when `_meta_charts_on()`
  - `worldstate_trajectory` → `build_worldstate_area` (:2149)
- Price history (:4607-4630): if there are no Plotly price items or any of them lacks a PNG, it
  re-renders all of them with matplotlib `render_market_price_history` (:2656). Each result is
  matched to a Plotly item by file stem; otherwise it is appended as a png item.
- `comparison` → `build_comparison_bars` (:2558) and `calibration` → `build_calibration_curve`
  (:2610) run whenever their data is present. They have no Plotly equivalent. Missing data gives
  `no_input`; a `None` result gives `empty_after_parse` (:4632-4660).

### Persistence helpers

**`_write_mermaid(charts_dir, stem, block)`** (staticmethod, :4664-4678)
- Writes `charts/<stem>.mmd` atomically. Returns the relative path, or `None` on failure.
- **No callers anywhere** (grepped `backend/`), so it is dead code.

**`_persist_manifest(report_dir, items, skipped=None, provenance=None)`** (staticmethod, :4680-4703)
- Writes `reports/<id>/viz_manifest.json` as
  `{"schema_version": 2, "items": items, "skipped": skipped or []}`, plus `"provenance"` when it is
  a non-empty dict.
- Uses `ensure_ascii=False` and `indent=2`, and writes atomically through `.tmp` and `os.replace`.
  A failure is only a debug log.

**`_manifest_provenance(artifacts)`** (staticmethod, :4705-4745)
- For each artifact key (sorted), it computes the sha256 of
  `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` and stores it in
  `inputs_sha256`. Values that cannot be serialized go into `unhashed_inputs`.
- `policy = {"renderer": "report_visualizer", "theme": "WAVE9", "schema_version": 2, "plotlyjs_inline": <knob>}`,
  plus `policy_sha256`.
- Any failure returns `{}`, and the provenance key is then omitted.

**`_load_price_history(report_dir, artifacts)`** (staticmethod, :4747-4777)
- Merges `{market_id: list}` from three sources in priority order:
  1. `artifacts["market_price_history"]` (a dict)
  2. `<report_dir>/market_price_history.json`
  3. `<artifacts["handoff_dir"]>/market_price_history.json`
- Lower-priority sources only fill missing keys. Non-list values are ignored. A broken file is
  skipped. Returns `{}` if nothing is found.

### Module-level pure helpers

**`_CAUSAL_STR_RE`** (:4784) matches `A --[inner]--> B`.

**`_parse_causal_item(item)`** (:4787-4838)
- A string has the form `A --[TYPE,sign,strength]--> B`. The type maps through `_REL_LABEL_EN`
  (:1736) and the sign through `_SIGN_TOKEN` (:1745). Any extra that is not a sign is treated as
  strength.
- A dict may carry `path`/`nodes`, which become pairwise multi-hop edges, or `source`/`from` and
  `target`/`to`.
- Returns a list of `(src, tgt, label)`. Invalid input returns `[]`.
- Used only by the Mermaid causal helper (:1848), which `build_all` no longer emits.

**`_normalize_clusters(coalition)`** (:4841-4866)
- Accepts a dict with `clusters`, `coalitions`, `factions` or `groups`, or a list.
- Members come from `members`, `agents` or `names`, or the item itself if it is a list, tuple or
  set. The label defaults to "Faction i".
- Used only by `render_mermaid_coalition` (:1884).

**`_first_float(d, keys)`** (:4869-4878) returns the first key present whose value parses with
`_to_float` (:673). `_to_float` extracts the first numeric token, so `"37%"` becomes 37.0, not
0.37.

**`_normalize_price_anchors(anchors, price_history)`** (:4881-4935)
- Each item may be a binary forecast with a `market_anchor` or an already-flattened dict.
- `market_id` comes from the anchor, falling back to the item. Anchors are deduplicated in
  first-seen order.
- The series must be a list of at least 2 entries `{t, p}`:
  - `t` is a float converted with `datetime.utcfromtimestamp`; overflow and invalid values are
    skipped.
  - `p` is clamped to [0, 1].
  - After filtering, at least 2 points must remain, and they are sorted by time.
- `model_p` comes from `probability`, `model_prob`, `model_p` or `p`.
- `market_p` comes from `implied_yes_prob` or `implied_prob`, falling back to the last point in
  the series.
- `divergence` is the anchor's value, else `model_p - market_p`.
- `label` is `_mpl_text(id, statement, label or market_id, max 52)`.

**`_SCENARIO_INTERVAL_STYLES / _ORDER / _TITLES`** (:4942-4975) give each interval source its
label, colour, matplotlib marker, Plotly symbol and cap width:

| source | label | colour | marker | Plotly symbol | cap |
|---|---|---|---|---|---|
| ensemble | Ensemble spread | #2b2b2b | o | circle | 5 |
| declared | Declared uncertainty interval | #b26a00 | D | diamond | 4 |
| self_consistency | Self-consistency spread | #4a3aa7 | s | square | 4 |

**`_scenario_rows_with_interval`** (:4978) keeps the rows where lo and hi are present and
`hi > lo`.

**`_scenario_interval_title`** (:4986-4995) returns the per-source title when there is a single
source, "(intervals by source)" when there are several, and plain "Scenario Probabilities"
otherwise.

**`_scenario_interval_subtitle(rows, forecast)`** (:4998-5022)
- No intervals: "point estimates only — no interval data supplied".
- Self-consistency only: uses `forecast.interval_provenance.{k,spread}`, falling back to
  `forecast.self_consistency_k` and `self_consistency_mean_spread`, to produce "±X.Xpp spread from
  k=K self-consistency draws".
- Ensemble only: "min–max across ensemble runs".
- Declared only: "declared p_low–p_high from forecast.json".
- Otherwise: "mixed provenance".
- When only some rows have intervals, it appends "; unmarked bars are point estimates".

**`_extract_scenario_rows(forecast, ensemble=None)`** (:5025-5161), the scenario contract:
- `_probability` accepts only values in [0, 1] (:5042-5046).
- **Canonical path** (forecast scenarios present, :5080-5129). For each canonical scenario with a
  valid p:
  - Find an unused ensemble row whose ID (`id`, `scenario_id`, `scenarioId` or `slug` passed
    through `_norm_key`) or whose normalized name, label or alias matches exactly (:5048-5060,
    :5089-5095). Each ensemble row matches at most once.
  - With a match, use the ensemble row's `min`/`max` (or `p_low`...) if they bracket the canonical
    p; the source is then "ensemble", and stdev and support are kept.
  - Otherwise use the canonical scenario's own bounds. The source is "self_consistency" if
    `interval_source == "self_consistency_spread"`, else "declared" (:5102-5115).
  - Rows are never appended from the ensemble.
- **Ensemble-only path** (:5130-5157): p comes from `probability`, `prob`, `p`, then
  `mean_probability`. The whole result is discarded (returns `[]`) if the sum of p is outside
  [0.95, 1.05].
- Sorted by `(-p, name)` and **capped at 14**. Any exception returns `[]`.

**`_scenario_data_present(forecast, ensemble)`** (:5164-5172) is True for non-empty ensemble
scenarios, non-empty forecast scenarios, or a non-empty forecast list.

**`_FLEX_DATE_RE`** and **`_QUARTER_DATE_RE`** (:5175-5176).

**`_parse_flex_date(s)`** (:5179-5217)
- `YYYY-Qn` or `YYYY-Qn-Qm` becomes the midpoint of the quarter range.
- `YYYY` becomes June 15; `YYYY-MM` becomes the 15th of that month; `YYYY-MM-DD` is exact.
- The year must be in [1900, 2200]. Any other format (ISO datetime with a time part, slashes,
  month names) returns `None`.

**`_flex_date_precision(s)`** (:5220-5232) returns quarter_range, quarter, day, month, year or
unknown.

**`_trajectory_row_date(row)`** (:5235-5251) applies strict `date.fromisoformat` to
`(as_of or period_end)[:10]`, and returns `None` on failure.

**`_TL_CATEGORIES`** (:5259-5281) defines five keyword lanes in precedence order: Policy &
Regulation, Geopolitics, Consumer & Adoption, Supply Chain & Economics, Companies & Technology.
**`_tl_category`** (:5284-5289) returns the first lane whose keyword is a substring of the
lower-cased text, else "Other".

**`_prepare_timeline_events(rows)`** (:5292-5329)
- Field names: date from `date`, `日期` or `when`; text from `event`, `事件`, `text`, `label` or
  `description`.
- Rows with no text or no date that `_parse_flex_date` can parse are **dropped**.
- Same-date events are deduplicated when token Jaccard is at least 0.55, keeping the first.
- `score` is 1 if the text contains a digit or a `$%€¥` symbol, plus `min(len/160, 1)`.
- The list is capped at `REPORT_VIZ_TIMELINE_MAX_EVENTS` (default 40) by highest score, then
  sorted by `(dt, text)`.

**`_norm_key`** (:5332-5334) casefolds, collapses whitespace and strips the characters
`.,;:'"()`.

**`_canonical_actor_map`** (:5337-5357) maps the normalized name and its aliases to the canonical
name. The first alias claim wins.

**`_canonicalize(name, canon)`** (:5360-5375)
- An exact key match (including aliases) wins first.
- Otherwise it looks for **character-substring** containment in either direction, with both keys
  at least 4 characters. It picks the longest canonical name, ties broken alphabetically.
- If nothing matches, it returns the raw name.

**`_network_layout(nodes, edges)`** (:5378-5411)
- With networkx: `spring_layout(seed=7, k=0.9/√n, iterations=60)`.
- Without networkx, or on error, a deterministic concentric fallback is used:
  - Nodes are sorted by `(-degree, name)`.
  - Ring radius is `0.35 + 0.55*ring`.
  - Ring capacity starts at 6 and is multiplied by 1.8 (as an int) for each new ring.

## Control flow

```
report_agent finalize (report_agent.py:11513-11521, if Config.REPORT_VISUALIZATIONS)
  └─ _inject_visualizations (report_agent.py:8882)   [returns early if markdown is empty]
      ├─ _collect_viz_artifacts (report_agent.py:8926-8999)
      └─ ReportVisualizer().build_all(report_id, folder, artifacts)   (:4313)
           ├─ gate REPORT_VISUALIZER (:4344)
           ├─ reset batch state, _batch_mode=True (:4350-4354)
           ├─ _attempt × builders (:4394-4491)
           │     └─ build_*_html → _save_pair (:2906) → _save_html (:2793)
           │                         ├─ _ensure_plotly_bundle (:2753)
           │                         └─ _inject_plotly_load_guard (:2774)
           │                     → _queue_png (:2844) [queued, batch mode]
           │     └─ density gate → _write_density_fallback (:2887) → _skip_notes
           ├─ price history: _load_price_history (:4748) → render_market_price_history_html (:3170)
           ├─ finally _batch_mode=False (:4522)
           ├─ _flush_png_jobs (:2856): pio.write_images, else per-image _save_png (:2823, breaker)
           ├─ attach png_path (:4526-4529)
           ├─ _run_matplotlib_family (:4547) → matplotlib builders (part 1) for missing PNGs
           │                                    and comparison/calibration
           ├─ _persist_manifest (:4681) + _manifest_provenance (:4706)
           └─ INFO summary (:4541)
      └─ _place_visualizations (report_agent.py:9043) → _render_viz_block (report_agent.py:9106)
           html item: embed png_path image if present, else link to the HTML
```

When a builder is called directly (outside `build_all`), `_batch_mode` is False, so `_queue_png`
renders the PNG immediately (:2851-2854).

## Data & artifacts

**Written** (all under `reports/<id>/`):

| path | format | written by |
|---|---|---|
| `charts/plotly.min.js` | shared Plotly JS bundle, about 4.9MB, written once per charts directory | :2759-2767 |
| `charts/<stem>.html` | full HTML; in directory mode it references `plotly.min.js` and carries the load guard, `<title>` and favicon | :2809-2817 |
| `charts/<stem>.png` | kaleido output at scale 2 and width 1200 | :2836 / :2873; matplotlib fallback writes the same names (:1982-1988) |
| `charts/<stem>_table.md` | markdown table when a chart falls below the density gate | :2896-2900 (only `model_vs_market` and `quantitative_claims`) |
| `viz_manifest.json` | `{schema_version: 2, items, skipped, provenance?}` | :4688-4701 |

Possible stems: `scenario_probabilities`, `binary_forecast_dotplot`, `model_vs_market`,
`timeline_lanes`, `actor_network`, `source_mix_sunburst`, `metric_trajectories`,
`technology_shares`, `regional_comparison`, `quantitative_claims`, `forecast_revisions`,
`worldstate_trajectory`, `market_price_history_<n>`; and, only when called directly,
`actor_influence_salience`, `driver_tornado`, `contested_claims`. The matplotlib-only charts are
`comparison_bars.png` and `calibration_curve.png`.

**Manifest item:** `{id, path, type: "html"|"png", title, caption (same as title), source, placement_hint, png_path?}`.
**Skipped entry:** `{builder, reason, fallback_path?}`. Reasons:
- `plotly_unavailable_or_disabled`
- `no_input`
- `exception:<Type>`
- `empty_after_parse`
- `below_density_threshold`
- `methodology_not_reader_facing`
- `internal_proxy_not_reader_facing`
- `proxy_not_sensitivity_analysis`
- `proxy_evidence_weight_not_reader_facing`
- `disabled`
- `matplotlib_unavailable_or_disabled`

**Provenance:** `{inputs_sha256: {key: hex}, policy: {...}, policy_sha256, unhashed_inputs?}`
(:4736-4743).

**Read:**
- `artifacts` dict keys: `forecast`, `ensemble`, `timeline`, `actors`, `quantitative`, `sources`,
  `contested`, `graph_priors`, `graph_priors_structural`, `world_state_trajectory`, `comparison`,
  `calibration`, `market_price_history`, `handoff_dir`.
- `<report_dir>/market_price_history.json` and `<handoff_dir>/market_price_history.json`, both
  `{market_id: [{t: unix_seconds, p}]}` (:4766-4776).

**In-memory state** (initialized at :1779-1788, reset at :4350-4354):
- `_png_jobs`: list of `(fig, abs, rel, item_id)`
- `_png_done`: dict `item_id → rel png`
- `_batch_mode`
- `_kaleido_failed` (written, never read)
- `_skip_notes`: dict `item_id → note`
- The module global `_KALEIDO_RUNTIME_OK` (:186).

## Config / env knobs

| name | default | effect | anchor |
|---|---|---|---|
| REPORT_VISUALIZER | True (Config, `backend/app/config.py:203`) | false: `build_all` returns `[]` and writes nothing | :4344 |
| REPORT_VIZ_INTERACTIVE | True (`config.py:217`) | turns the whole Plotly family on or off | :2744 |
| REPORT_VIZ_PNG_EXPORT | True (`config.py:221`) | turns kaleido PNG export on or off | :2749 |
| REPORT_VIZ_PLOTLYJS_INLINE | False (`_cfg` default; **not defined in Config**) | inlines Plotly JS in every chart; also recorded in `provenance.policy` | :2806, :4731 |
| REPORT_VIZ_MAX_NODES | 40 (`config.py:212`) | anchor cap for price history; `or 40` means 0 becomes 40, and a value of 0 or less disables the cap | :3186-3188 |
| REPORT_VIZ_NETWORK_MAX_NODES | 60 (`config.py:225`) | node cap for the actor network, `max(2, cap)` | :3513-3518 |
| REPORT_VIZ_TIMELINE_MAX_EVENTS | 40 (`config.py:223`) | cap on timeline events, keeping the highest scores | :5325-5327 |
| REPORT_META_CHARTS | off (not in Config; falls back to `os.environ`, accepting 1/true/yes/on) | restores `actor_network` and `source_mix_sunburst` (and the matplotlib `actor_network` fallback) | :211-220, :4417, :4438, :4596 |
| REPORT_VIZ_PRICE_HISTORY | True (not in Config; env fallback counts only "true" as true) | turns the price-history family on or off (Plotly and matplotlib) | :1965-1973, :4494, :4610 |
| REPORT_VIZ_CHARTS | True (`config.py:208`) | turns the matplotlib fallback family on or off (`_chart_ok`) | :1962-1963, :4557 |
| REPORT_VIZ_DPI | 160 (`config.py:210`) | dpi of matplotlib fallback PNGs | :1976-1980 |
| Import probes `PLOTLY_AVAILABLE`, `KALEIDO_AVAILABLE`, `NETWORKX_AVAILABLE`, `MATPLOTLIB_AVAILABLE` | set at import time | decide whether each family runs or degrades | :141-184 |
| `_KALEIDO_RUNTIME_OK` | True | tripped for the life of the process on the first per-image kaleido failure | :186, :2839 |

The REPORT_VISUALIZATIONS knob (`backend/app/config.py`, read at `report_agent.py:8893` and
`:11517`) gates the only production call site, so it also turns off generation, not just
injection.

## External calls

- **No LLM, HTTP, DB or provider calls** anywhere in the slice.
- **Subprocess, indirectly:**
  - `fig.write_image` (:2836) and `plotly.io.write_images` (:2873) use kaleido v1, which drives a
    local Chrome or Chromium through choreographer. Installed versions: kaleido 1.3.0 and
    plotly 6.9.0 in `backend/.venv`; `backend/pyproject.toml:45-47` requires `plotly>=5.18.0`,
    `kaleido>=1.3.0`, `matplotlib>=3.7.0`.
  - This is the only place the slice launches an external process.
- **Libraries:**
  - `plotly.graph_objects`, `plotly.subplots.make_subplots` (lazy imports at :3804, :3890, :3937,
    :4026, :4100), `plotly.offline.get_plotlyjs` (:2763), `plotly.io` (:2864).
  - `networkx.spring_layout` (:5388).
  - `datetime` and `calendar` (lazy imports at :4894, :5186-5187, :5242).
  - `hashlib`, used by the provenance hasher.
- **Filesystem:** all writes are atomic `.tmp` + `os.replace`, except the PNGs, which kaleido and
  matplotlib write directly.

## Cross-module edges

**Callers into this slice:**
- `backend/app/services/report_agent.py:8906` calls `ReportVisualizer().build_all`, with
  artifacts from `_collect_viz_artifacts` (`report_agent.py:8926-8999`). That function supplies:
  - forecast (the file `forecast.json`, or the in-memory spine with `market_comparison` merged in)
  - comparison
  - actors
  - ensemble (`ensemble_forecast.json`)
  - quantitative, sources, contested, graph_priors and graph_priors_structural (in memory)
  - world_state_trajectory (`OASIS_SIMULATION_DATA_DIR/<sim>/world_state_trajectory.json`)
  - timeline
  - handoff_dir

  It **never supplies `calibration` or `market_price_history`**.
- `backend/scripts/backfill_report_visuals.py:503` calls `build_all` with artifacts from
  `_artifacts()` (`backfill_report_visuals.py:340-361`). That includes `prediction_markets`, which
  `build_all` never reads (it is only hashed), and also no `calibration`.
- Tests that import `ReportVisualizer` include `backend/tests/test_wave9_visualizer.py`,
  `test_report_visualizer.py`, `test_viz_manifest_provenance.py`, `test_sessionb_viz_signal.py`,
  `test_sessionb_forecast_charts.py`, `test_loop006_static_viz_fallbacks.py`,
  `test_report_chart_quality.py`, `test_report_visualizer_axes.py`, `test_report_viz_and_pdf.py`
  and `test_backfill_report_visuals.py` (grep of `backend/tests`).
- Inside the same file, the matplotlib builders reuse helpers from this slice:
  `_extract_scenario_rows`, `_SCENARIO_INTERVAL_*`, `_scenario_interval_title/subtitle`
  (:2009-2068), `_trajectory_row_date` (:2186), `_prepare_timeline_events` and `_TL_CATEGORIES`
  (:2240-2244), `_canonical_actor_map`, `_canonicalize`, `_network_layout` and `_norm_key`
  (:2374-2443), `_first_float` (:2627), and `_normalize_price_anchors` (:2679). The Mermaid
  helpers use `_parse_causal_item` (:1848) and `_normalize_clusters` (:1884).

**Consumers of the outputs:**
- `report_agent._place_visualizations` and `_render_viz_block` (`report_agent.py:9043`, `:9106`).
  An `html` item is embedded as its `png_path` image when that file exists; otherwise the markdown
  gets a link. Placement uses `_VIZ_PLACEMENT_KEYWORDS` (`report_agent.py:8696`).
- `backend/app/api/report.py:1279` (`get_report_chart`) serves `charts/*`. For `.html` it calls
  `inline_plotly_bundle` (`backend/app/utils/chart_html.py:30`), which inserts the sibling
  `plotly.min.js` in place of the script tag. It then applies a `sandbox allow-scripts` CSP. Its
  allowed extensions (`api/report.py:1300`) exclude `.md`.
- `backend/app/api/report.py:1358` (`get_report_viz_manifest`) normalizes `items` and passes
  `skipped` through.
- `backend/app/services/pipeline_orchestrator.py:9560` (an integrity spec) and `:9631`
  (`_validate_report_viz_references`) check every item's `path` and `png_path`: each must exist,
  be non-empty and not be a symlink.
- `report_agent.py:12759` records `viz_manifest_sha256`.
- `backend/app/services/exec_brief.py:341` (`_find_scenario_chart`) reads the manifest **only as a
  legacy list**.
- Frontend: `frontend/src/utils/vizManifest.js:40` and
  `frontend/src/components/research/ForecastReport.vue:813` fold `png_path` into chart cards.

**Calls out from the slice:**
- Helpers before the slice: `_cfg` (:202), `_meta_charts_on` (:211), `_apply_layout` (:304),
  `_wrap_hover` (:321), `_tokens`/`_jaccard` (:346/351), `_mpl_text` (:376), `_timeline_label_plan`
  (:496), `_actor_label_plan` (:550), `_html_text` (:607), `_wrap_label` (:623), `_md_cell` (:660),
  `_to_float` (:673), `_prepare_quantitative_panels` (:1055), `_metric_trajectory_panels` (:1489),
  `_prepare_technology_shares` (:1502), `_prepare_regional_comparison` (:1566),
  `_prepare_forecast_revision_series` (:1634), `_sign_of` (:1752).
- The matplotlib builders (:1997-2730), and `backend/app/config.Config` through `_cfg`.

## Invariants, gates, validation

- **No public builder raises.** Every builder wraps its body in `try/except`. `_attempt` adds a
  second guard (:4373-4379).
- **Every builder that does not produce output gets a `skipped` entry in `build_all`**, apart from
  the matplotlib `_fallback` failures (:4570-4574), which are dropped silently.
- **The canonical scenario distribution comes first.** Ensemble rows add uncertainty only when
  their ID or name matches exactly, and are never appended (:5080-5129).
- **Ensemble-only distributions must sum to between 0.95 and 1.05**, or no chart is produced
  (:5155-5157).
- **Probabilities outside [0, 1] are dropped** for scenarios (:5042-5046). Binary dotplot
  probabilities are not range-checked (:3248).
- **An interval is drawn only if `lo <= p <= hi` and `hi > lo`** (:5065, :2950-2964).
- **Density gates:** model-vs-market needs at least 3 anchored rows (:3050). A quantitative panel
  needs at least 4 points or at least 2 metrics (:3994).
- **Binary confidence is encoded only when every row declares a confidence in [0, 1]**
  (:3252, :3276).
- **The world-state calendar axis needs a valid ISO date on every row** (:3143).
- **Price-history anchors need at least 2 valid points**, and p is clamped (:4905, :4919-4920).
- **Determinism:** fixed sort keys everywhere, `spring_layout(seed=7)`, and the concentric
  fallback layout.
- **Atomic writes** for the HTML, the bundle, the tables and the manifest.

## Failure modes & recovery

| failure | behaviour | anchor |
|---|---|---|
| plotly not installed, or `REPORT_VIZ_INTERACTIVE` off | every Plotly builder is skipped with `plotly_unavailable_or_disabled`; matplotlib supplies PNG items where an equivalent exists | :4367-4369, :4547 |
| kaleido missing or PNG export off | the HTML is kept; the matplotlib fallback attaches a `png_path` for scenario, model-vs-market, timeline, world state and price history; the other charts are HTML only | :4564-4605 |
| kaleido batch call raises | falls back to per-image export | :2878-2885 |
| kaleido per-image call raises | trips the process-wide breaker; no later PNGs in this process | :2838-2842 |
| bundle write fails | the chart is written with Plotly JS inline | :2807-2808 |
| bundle not delivered (directory mode) | the in-page guard shows a red notice | :2774-2791 |
| HTML write fails | `None`, then skip `empty_after_parse` | :2819-2821, :4380-4385 |
| manifest write fails | debug log only; the charts remain on disk | :4702-4703 |
| provenance fails | `{}`; the manifest has no provenance key | :4744-4745 |
| broken price-history file | that file is skipped | :4775-4776 |
| networkx missing or layout error | concentric fallback | :5390-5411 |
| exception in `build_all` itself (outside `_attempt`) | `finally` resets batch mode; the exception reaches `report_agent`, which logs a warning and skips the charts | :4521-4522, `report_agent.py:8905-8909` |

## Surprises

1. **(suspected bug) `REPORT_VIZ_PLOTLYJS_INLINE` cannot be turned on through the environment.**
   `_cfg` only reads `Config` attributes (:202-208), and `backend/app/config.py` does not define
   `REPORT_VIZ_PLOTLYJS_INLINE` (grep finds no hits). Setting the env var documented at
   `.env.example:588` does nothing. Contrast `_meta_charts_on` (:215-217) and `_price_hist_ok`
   (:1968-1973), which fall back to `os.environ`.
2. **(suspected bug) The matplotlib price-history fallback attaches the wrong PNGs when there are
   more than 6 anchors.**
   - The Plotly path writes one chart per anchor, as `market_price_history_{i}` (:3190-3219).
   - The matplotlib path groups 2 anchors per figure when there are more than 6 anchors, so
     `market_price_history_{g}` means group g (:2691-2725).
   - `_run_matplotlib_family` matches by stem (:4618-4622). Plotly item 1 therefore gets a PNG
     showing anchors 1 and 2, item 2 gets anchors 3 and 4, and the later items get no PNG.
   - Because the file names are shared, a matplotlib re-render can also overwrite kaleido PNGs
     that are already attached to other items. That happens when only some kaleido exports
     succeeded, since `need_ph` re-renders the whole set (:4609).
3. **(suspected) The kaleido circuit breaker is process-wide and never resets.** One transient
   Chrome failure turns off PNG pairs for every later report in the long-running Flask process.
   `build_all` resets only `self._kaleido_failed` (:4353), which is never read anywhere (written
   at :1785, :2840, :4353). In addition, `global _KALEIDO_RUNTIME_OK` in `_flush_png_jobs` (:2859)
   is never assigned.
4. **(suspected) Density-gate tables are orphaned.** `charts/*_table.md` is written and
   `fallback_path` is recorded in `skipped[]` (:2887-2904). However, no backend or frontend code
   reads `fallback_path` or `below_density_threshold` (grep of `backend/app` and `frontend/src`).
   The chart route's allowed extensions also exclude `.md` (`backend/app/api/report.py:1300`).
   Readers never see the "compact table instead".
5. **Dead or unreachable code in the default path.**
   - `_write_mermaid` (:4664) has no callers.
   - `build_actor_bubble_html`, `build_driver_tornado_html` and `build_contested_dumbbell_html` are
     always skipped by `build_all` (:4430, :4475, :4483). They are reachable only by calling them
     directly.
   - `cont = artifacts.get("contested")` (:4479) is assigned but never used.
   - `_parse_causal_item` and `_normalize_clusters` serve only the Mermaid helpers, which
     `build_all` no longer emits.
6. **(suspected) `calibration_curve` is effectively always skipped with `no_input`.** Neither
   production caller puts a `calibration` key into `artifacts` (`report_agent.py:8926-8999`;
   `backfill_report_visuals.py:340-361`). The `market_price_history` artifact key is never
   supplied either, so only files are used for it.
7. **Doc-vs-code drift.**
   - `DRF_ARCHITECTURE.md:1282-1301` says `build_all` (cited at `:2534`, actually :4313) registers
     the actor network, influence×salience bubble, source sunburst, driver tornado and contested
     dumbbell. In code these are skipped by default (opt-in or always).
   - The module docstring (:18-19), `.env.example:267` and `backend/requirements.txt:47` still say
     each chart is "plotly.js 内联、完全离线自包含" (Plotly JS inlined, fully self-contained
     offline). The code defaults to directory mode with a shared bundle (:2807-2808).
   - `.env.example:269` calls REPORT_VISUALIZATIONS orthogonal to generation. Yet `build_all` is
     only reached through `_inject_visualizations`, which returns early when REPORT_VISUALIZATIONS
     is off or the markdown is empty (`report_agent.py:8893-8897`).
8. **(suspected) `exec_brief._find_scenario_chart` ignores schema-v2 manifests.** It handles only
   `isinstance(manifest, list)` (`backend/app/services/exec_brief.py:344-353`). With the v2 dict it
   always falls back to the conventional `charts/scenario_probabilities.png`, which happens to be
   the kaleido or matplotlib filename.
9. **(suspected) Timeline dates in many formats are silently dropped.** `_parse_flex_date` accepts
   only `YYYY`, `YYYY-MM`, `YYYY-MM-DD` and quarter forms (:5175-5217). ISO datetimes such as
   `2025-03-15T00:00:00Z`, slashed dates and month names return `None`, and the row is removed
   (:5306-5308). The fallback `date_raw or dt.strftime(...)` at :5319 is unreachable, because
   `date_raw` is always non-empty when `dt` parsed.
10. **(suspected) Price-history timestamps in other formats are misplotted or dropped.**
    `_to_float(pt["t"])` takes the first numeric token (:673-698). An ISO string such as
    `"2025-03-01"` becomes `2025.0`, which is about 34 minutes after the Unix epoch in 1970. A
    millisecond epoch overflows and is dropped. `datetime.utcfromtimestamp` (:4916) is deprecated
    on the Python 3.12 venv.
11. **(suspected) `_canonicalize` can merge unrelated actors.** It uses character-substring
    containment with a 4-character minimum (:5368-5374), so "Ford" could merge into "Oxford
    University" or "Intel" into an "Intelligence ..." name. The docstring's "merge only on a
    unique hit" also conflicts with the code, which picks the longest of several hits.
12. **(suspected, cosmetic) Escaping mismatches in Plotly titles.**
    - Price-history labels go through `_mpl_text` (:4930), which escapes a pair of `$` as `\$`
      for matplotlib. The Plotly title (:3212) would then show literal backslashes.
    - The forecast-revisions subplot titles (:4103) skip `_html_text`, so a pair of `$` there could
      trigger MathJax.
13. **The provenance policy hash covers only `plotlyjs_inline`** (:4727-4732). Knobs that change
    the item set, such as REPORT_META_CHARTS, PNG_EXPORT, the caps and the matplotlib toggles, are
    not hashed, so equal `policy_sha256` values do not mean equal rendering policy.
14. **The bundle is reused without a version check** (:2760). After a plotly upgrade, a backfill
    into an existing `charts/` directory keeps the old `plotly.min.js` next to HTML produced by the
    new plotly.py. **`build_all` also never cleans `charts/`**, so stale HTML, PNG and `_table.md`
    files from earlier runs remain on disk unreferenced. When REPORT_VISUALIZER is off, the old
    `viz_manifest.json` is left in place (:4344-4345).
15. **`_to_float("37%")` returns 37.0.** Percent strings are silently rejected as scenario
    probabilities (:5044) and clamped to 1.0 in price history (:4919). In the binary dotplot they
    would plot far outside the [0, 1] axis (:3248, :3331).
16. **`networkx` is listed in `backend/requirements.txt:56` but not in `backend/pyproject.toml`.**
    plotly, kaleido and matplotlib are listed there (:43-47). If no other package pulls networkx
    in transitively, `uv sync` may remove it, and the actor network silently switches to the
    concentric layout (:5382-5411). This is unverified, because `backend/uv.lock` is deleted in
    this checkout.
17. **Duplicate config defaulting.** `or 40`, `or 60` and `max(2, cap)` mean a cap of 0 cannot
    turn off the network or price caps. A negative network cap keeps only 2 nodes (:3513-3518).
