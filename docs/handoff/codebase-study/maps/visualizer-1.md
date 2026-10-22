# visualizer-1 — report_visualizer.py part 1

Slice: `backend/app/services/report_visualizer.py` lines 1-2741 (file is 5,411 lines; part 2 = 2742-5411 belongs to another reader).
Checkout studied: branch `main`, on-disk working tree at `/Users/rogerlin/Downloads/DeepResearchForecast` (2026-10-11).

**Anchor convention.** `L123` means `backend/app/services/report_visualizer.py:123`. Every other anchor uses its full repo-relative path. Where a claim depends on code outside this slice (part 2 of the same file, or another module), the anchor points to that code and says so. Behaviors marked "(verified)" were checked by running the pure helpers, which were pulled out of the source with `ast` into an isolated namespace. That did not import the package and had no side effects.

---

## Purpose & position in the pipeline

`report_visualizer.py` is DRF's **deterministic, LLM-free chart renderer** (module docstring L1-46). It runs at the end of the report stage. `ReportAgent.generate_report` (`backend/app/services/report_agent.py:11113`) calls `_inject_visualizations` (`backend/app/services/report_agent.py:11517-11521`). That method collects already-persisted artifacts with `_collect_viz_artifacts` (`backend/app/services/report_agent.py:8926-8999`): forecast.json, ensemble_forecast.json, comparison.json, in-memory actors/quantitative/sources/contested/graph priors, the simulation's world_state_trajectory.json, timeline, and handoff_dir. It then calls `ReportVisualizer().build_all(report_id, folder, artifacts)` (`backend/app/services/report_agent.py:8906`). `build_all` itself lives in part 2 (L4313-4545). It writes `reports/{id}/charts/*` and `reports/{id}/viz_manifest.json`, and `report_agent._place_visualizations` (`backend/app/services/report_agent.py:9043`) then splices the charts into `full_report.md`. The offline repair script `backend/scripts/backfill_report_visuals.py:503` also calls `build_all`.

Part 1 (this slice) contains:

1. **Module plumbing.** Zh chart-title localization for translated reports (L63-106). Plotly HTML title and favicon finalizers that part 2's `_save_html` uses (L108-135). Optional-dependency probes for matplotlib, plotly, networkx and kaleido (L137-186). The `_cfg` Config reader and the `REPORT_META_CHARTS` gate (L199-220).
2. **Shared style and text helpers** used by both chart families: the palette, `_apply_layout`, hover/label wrappers, and Mermaid/matplotlib/HTML text sanitizers (L223-393, L607-670). CJK font discovery for matplotlib (L396-486). Deterministic label-collision planners for timeline and network charts (L489-604).
3. **Data-preparation functions** (pure) for the "quantitative" research artifact: numeric parsing, unit comparability, the publishability floor, same-denominator benchmark panels, metric trajectories (DRF2 `metric_family` path plus the legacy folded-name path), technology shares, regional comparison, and forecast-revision vintages (L673-1732). The plotly builders in part 2 use them (e.g. L3801, L3887, L3934, L3989, L4097).
4. **Relationship sign/label tables** (L1735-1765).
5. **`ReportVisualizer` class, first half** (L1768-2741): the constructor's PNG-batch state, (A) four pure Mermaid helpers that production no longer calls, and (B) the **matplotlib PNG family**. That family has eight builders (scenario bars, model vs market, world-state area, timeline lanes, actor network, comparison bars, calibration curve, market price history). `build_all` uses them only as fallbacks when an interactive plotly chart has no kaleido PNG. Comparison bars and the calibration curve have no plotly equivalent and are always matplotlib (L4531-4535, L4632-4660). The section ends with the header comment that opens the plotly family (L2734-2740).

---

## Walkthrough (source order)

### Module docstring and imports (L1-61)
- **Docstring (L1-46).** Describes three families. (A) Mermaid helpers kept as library functions; `build_all` no longer emits Mermaid (L6-7). (B) matplotlib PNG fallback family, plus comparison bars and the calibration curve, which have no plotly equivalent (L8-9). (C) plotly HTML plus kaleido PNG as the primary family (L10-19). It lists the env knobs (L33-45) and states the design rules: Mermaid helpers never raise (L22-23); optional dependencies are probed at module level (L24-25); `build_all` returns manifest items and persists `{"schema_version":2,"items":[...],"skipped":[...]}` (L26-29); output is deterministic (L30-31).
- **Imports (L48-59).** `datetime as dt`, `hashlib` (used only in part 2, L4725), `html as html_lib`, `json`, `logging`, `math`, `os`, `re`, typing, `urlsplit`. `logger = logging.getLogger(__name__)` (L61).

### `CHART_TITLES_ZH` (backend/app/services/report_visualizer.py:67)
- Dict of 16 fixed English manifest titles mapped to Chinese (L67-84). The comment (L63-66) says pandoc prints the alt text as the figure caption in Chinese variants. `frontend/src/utils/vizManifest.js:100-117` (`ZH_CHART_CAPTIONS`) holds the identical table, and `backend/tests/test_report_zh_presentation.py:46,54` pins the two in sync and checks that every builder title is covered.
- Covers both "Model vs Market (binary forecasts)" (plotly title, L4406) and "Model vs Market" (matplotlib fallback manifest title, L4588), plus "Baseline vs Scenario" and "Calibration Curve" (L4639, L4653).

### `_CHART_IMAGE_RE` (backend/app/services/report_visualizer.py:86)
- `!\[([^\]\n]*)\]\((charts/[^)\s]+)\)`: matches markdown images whose target starts with `charts/`.

### `localize_chart_alt_text(markdown, lang)` (backend/app/services/report_visualizer.py:89)
- **Inputs:** a markdown string and a language code. **Output:** the markdown, with chart-image alt text replaced by its `CHART_TITLES_ZH` entry when one exists.
- Returns the input unchanged unless `lang == "zh"` exactly (L91). `zh-CN` would not match.
- Walks lines and toggles `in_fence` on any line whose stripped start is ```` ``` ```` or `~~~` (L101-103); it does not match fence types. Only lines outside fences that contain `](charts/` are rewritten (L104-105). Unknown titles are kept (L96).
- **Caller:** `backend/app/services/report_agent.py:7544-7545`, after translating a report into `tgt_code`.

### `_EMBEDDED_FAVICON`, `_plotly_document_title`, `_finalize_plotly_html` (backend/app/services/report_visualizer.py:108-135)
- `_EMBEDDED_FAVICON` (L108-113) is a data-URI SVG (dark rounded square with a cyan plus).
- `_plotly_document_title(fig, filename)` (L116-124) reads `fig.layout.title.text`, tolerating mocks (L118-121), strips HTML tags and collapses whitespace (L122-123). If the result is empty it falls back to a title-cased filename stem with `_` replaced by spaces (L124).
- `_finalize_plotly_html(raw_html, title)` (L127-135) returns the input unchanged when there is no `</head>` (case-insensitive, L129-130). Otherwise it injects `<title>` (HTML-escaped) and `<link rel="icon">` before the first `</head>` (L131-135).
- Only `_save_html` uses these (part 2, L2811).

### Optional-dependency probes (backend/app/services/report_visualizer.py:141-186)
- **matplotlib (L141-148).** `matplotlib.use("Agg")` runs before importing `pyplot` (L143-144). On success `MATPLOTLIB_AVAILABLE=True`. On any exception `plt=None` and the flag is False (L146-148).
- **plotly (L156-161).** `import plotly.graph_objects as go` sets `PLOTLY_AVAILABLE`.
- **networkx (L167-172).** Sets `NETWORKX_AVAILABLE`, which the `_network_layout` spring layout in part 2 uses (L5382).
- **kaleido (L180-184).** Checks importability only, with `importlib.util.find_spec("kaleido")`; Chromium is not started at import time.
- **`_KALEIDO_RUNTIME_OK = True` (L186).** A process-wide, one-way circuit breaker. Part 2 sets it to False on the first kaleido render exception (L2839) and never resets it for the life of the process.

### `_close_matplotlib_figure(fig)` (backend/app/services/report_visualizer.py:189)
- Closes one specific figure with `plt.close(fig)` and swallows errors (L191-196). The docstring says this avoids touching concurrent callers' figures (L190). Every matplotlib builder's `finally` calls it. This double-closes after `_save` has already closed the figure, which is harmless.

### `_cfg(name, default)` (backend/app/services/report_visualizer.py:202)
- Lazily imports `..config.Config` and returns `getattr(Config, name, default)`. Any exception (for example, running outside the package) returns `default` (L204-208).
- **It never reads `os.environ`.** A knob that is not declared as a `Config` attribute always takes its code default. See Surprises for `REPORT_VIZ_PLOTLYJS_INLINE`.

### `_meta_charts_on()` (backend/app/services/report_visualizer.py:211)
- Reads `_cfg("REPORT_META_CHARTS", None)`. If that is None (Config has no such attribute; `backend/app/config.py` does not define it), it falls back to `os.environ["REPORT_META_CHARTS"]` (L215-217). Strings are true only if in `{"1","true","yes","on"}` (L218-219); other values use `bool(val)` (L220). The default is **off**.
- Gates the actor network and source-mix sunburst in `build_all` (L4417, L4438) and the actor-network matplotlib fallback (L4596).

### Style constants (backend/app/services/report_visualizer.py:228-257)
- `_VIZ_FONT` (L228-230): system-ui stack with CJK fallbacks (PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans CJK SC).
- `_PALETTE` (L231-232): 8 fixed categorical colors (`#2a78d6` blue first). `_SEQ_BLUES` (L233): 6-step sequential blues.
- Role colors (L234-245): `_COLOR_MODEL #2a78d6`, `_COLOR_MARKET #e34948`, `_COLOR_POS #1baf7a`, `_COLOR_NEG #e34948`, `_COLOR_NEU #b3b1a9`, `_COLOR_STALE #d03b3b`, `_COLOR_GOOD #0ca30c`, `_SURFACE #fcfcfb`, `_GRID #e1e0d9`, `_AXIS #c3c2b7`, `_INK #0b0b0b`, `_INK_2 #52514e`.
- `_LEVEL_NUM` (L248-249): maps very high/high/medium|med|moderate/low/very low to 4/3/2/1/0.5. Used by part 2's bubble chart (L3654-3659).
- Density gates (L251-257): `_MODEL_VS_MARKET_MIN_ANCHORED = 3`, `_QUANT_PANEL_MIN_POINTS = 4`, `_QUANT_PANEL_MIN_CATEGORIES = 2`.

### `_quant_panel_is_dense(panel)` (backend/app/services/report_visualizer.py:260)
- True if the panel has ≥4 rows (L262-263) or ≥2 distinct `metric` strings (L264-265). Used by `build_quantitative_dots_html` (L3994).

### `_quant_panel_subtitles(panels)` (backend/app/services/report_visualizer.py:268)
- Base title `"{unit} — as of {as_of} (n={len(rows)})"` (L271-275).
- When base titles collide, appends `time_basis` (≤20 chars) and the first row's metric (≤26 chars) joined by ` · ` (L276-289).
- Any titles that still collide get a deterministic ` (2)`, ` (3)` suffix (L290-296). Uses `zip(..., strict=True)` (L280), which requires Python 3.10+.

### Tier tables (backend/app/services/report_visualizer.py:299-301)
- `_TIER_RANK` S1..S4 → 0..3. `_TIER_COLOR` S1 darkest blue → S4 lightest. `_TIER_WEIGHT` 3/2/1/0.5.

### `_apply_layout(fig, title, height=520, **kwargs)` (backend/app/services/report_visualizer.py:304)
- Mutates a plotly figure in place:
  - Title is left-ish (x=0.02), size 16, `_INK`. Base font is size 12, `_INK_2`. Paper and plot background are `_SURFACE`. `colorway=_PALETTE`. Margins are l10/r24/t58/b46. Extra kwargs pass through to `update_layout` (L306-314).
  - Grid, zeroline and axis-line colors are set on both axes, with tick font 11 (L315-318).
- Used by every plotly builder in part 2.

### `_wrap_hover(text, width=64, max_len=480)` (backend/app/services/report_visualizer.py:321)
- Collapses whitespace and truncates to `max_len` with `…` (L323-327).
- HTML-escapes `& < >` (L328). If there are ≥2 `$`, replaces each with `&#36;` so MathJax does not treat the text as math (L330-331).
- Greedy word-wraps at `width` and joins lines with `<br>` (L332-343). Empty input gives `""`.

### `_tokens`, `_jaccard` (backend/app/services/report_visualizer.py:346-356)
- `_tokens`: set of lowercase `[a-z0-9]{2,}` tokens (L348). **ASCII only:** CJK text yields an empty set.
- `_jaccard`: |A∩B|/|A∪B|, or 0 if either set is empty (L353-356). Used by `_prepare_timeline_events` for same-day dedupe (L5309-5315) and by the driver tornado (L4172).

### `_san_label(text, max_len=80)` (backend/app/services/report_visualizer.py:359)
- Makes text safe inside a quoted Mermaid label:
  - `"`→`'`, `|`→`/`, CR/LF→space (L365).
  - `<`/`>` become full-width `＜`/`＞` (this replaced an older `>`→`)` substitution that broke text like `>$1T`; L366-368). `[`→`(`, `]`→`)`, `{`→`(`, `}`→`)`, `#`→`＃`, backtick→`'` (L368-369).
  - Collapses whitespace and truncates with `…` (L370-373).
- Verified: `'A "q" <b> [x] {y} #1 \`z\` | w'` → `A 'q' ＜b＞ (x) (y) ＃1 'z' / w`. It does **not** escape `:`.

### `_mpl_text(text, fallback="", max_len=60)` (backend/app/services/report_visualizer.py:376)
- Collapses whitespace and truncates. Empty input returns `fallback` (L384-389). With ≥2 `$`, escapes each as `\$` so matplotlib does not render mathtext (L391-392).
- The docstring (L377-383) records that CJK text used to be replaced by placeholders such as "Actor 4". Now font coverage is checked separately and the chart is skipped instead.

### CJK font machinery (backend/app/services/report_visualizer.py:396-486)
- `_CJK_FONT_FAMILIES` (L396-401): 14 family names (Noto Sans CJK SC/TC/JP, Source Han Sans, YaHei, SimHei, PingFang, Hiragino, Arial Unicode MS, WenQuanYi Zen Hei, Malgun Gothic).
- `_MPL_CJK_FONT_CACHE` (L402): a process-global cache, filled once.
- `_cjk_codepoints(text)` (L405-417): the frozenset of code points in CJK radicals/punctuation, kana, bopomofo, enclosed CJK, CJK Ext-A, Unified, Hangul syllables, compatibility ideographs, half/full-width forms (FF00-FFEF), and Ext B-H planes.
- `_installed_cjk_fonts()` (L420-454):
  - Returns the cached list if already filled (L423-424). If matplotlib is missing it caches `[]` (L426-428).
  - Otherwise, for each family it calls `font_manager.findfont(..., fallback_to_default=False)`, resolves the real path, dedupes paths, and reads the real charmap via `ft2font.FT2Font(path).get_charmap()`. It appends `(FontProperties(fname=path), frozenset(charmap))` (L435-446).
  - While probing, it temporarily raises the `matplotlib.font_manager` logger to ERROR and restores it in `finally` (L433-450). Failures are logged at debug (L451-452).
  - **Side effect:** reads system font files from disk.
- `_mpl_font_for_text(text)` (L457-469): returns None when the text has no CJK. Otherwise it returns the **first** font whose charmap ⊇ all required code points, or None if no single font covers them all.
- `_mpl_labels_supported(text)` (L472-474): true when the text has no CJK, or when some font covers all of it. Every matplotlib builder in this slice skips its chart (returns None or []) when this is False, and logs at INFO (e.g. L2033-2035, L2125-2127, L2197-2199, L2250-2252, L2454-2456, L2586-2588, L2686-2688). The calibration curve has no text labels and does no check.
- `_font_at_size(prop, size)` (L477-486): copies the FontProperties and sets its size. Returns None for None input, or the original on error.

### `_boxes_overlap(left, right, pad)` (backend/app/services/report_visualizer.py:489)
- Axis-aligned overlap test on `(x0, y0, x1, y1)` boxes with padding (L492-493).

### `_timeline_label_plan(events, used_index, max_labels=12)` (backend/app/services/report_visualizer.py:496)
- **Inputs:** prepared timeline events, each `{dt, text, score, cat}`, and `used_index` (lane name → lane row).
- **Output:** `{(dt, text): {label, offset, ha, va, bbox, index}}`.
- Returns `{}` when events or lanes are empty or `max_labels<=0` (L504-505).
- Ranks events by `-score`, then `dt`, then `text`, and keeps the top `max_labels` (L506-508).
- Builds an x span in date ordinals of at least 30 days (L509-511). Models the figure height as `max(3.8, 1.05*lanes+2.4)` (L513) and points per lane as `max(42, h*72*0.68/lanes)` (L514). Tries six vertical point offsets `(16,-20,34,-38,52,-56)` (L515).
- Label width is estimated as `max(5% span, span*min(0.25, 0.0055*len(label)))` (L527). Labels past 72% of the span extend leftward (L528-529).
- Takes the first collision-free slot with pad 0.01 (L530-544); labels with no free slot are omitted (docstring L500-502).
- Labels are normalized via `_mpl_text(..., max_len=48)` (L520).
- After placement, sequential `index` values from 1 are assigned in chronological order (L545-546).
- Callers: static timeline (L2248, default 12) and plotly timeline (L3361, `max_labels=10`).

### `_actor_label_plan(nodes, positions, weights, max_labels=22)` (backend/app/services/report_visualizer.py:550)
- Ranks nodes by `-weight`, then name, and keeps the top `max_labels` (L566). Labels use `_mpl_text(node, max_len=24)` (L569).
- Angles are radial from the centroid plus ±60°, 180°, ±90°, 0 and π (L573-579). A node exactly at the centroid gets a deterministic pseudo-angle from a weighted char-code hash (L574-576).
- Radii are tried at 0.07/0.12/0.18/0.25/0.34 × scale (L583). The half-width estimate is `max(4% x_span, x_span*min(0.18, 0.0065*len))` and the half-height is 2.5% of y_span (L580-581).
- A box is rejected if it overlaps a prior label (pad 0.8% scale, L590-592) or comes within 1.8% scale of **any** node marker (L594-597).
- Output: `{node: {label, xytext, bbox}}` (L598). Callers: static network (L2450, 22) and plotly network (L3561, 16).

### `_html_text(text, fallback="", max_len=60)` (backend/app/services/report_visualizer.py:607)
- Collapses whitespace and truncates. Empty input returns `fallback`. With ≥2 `$`, each becomes `&#36;` (L612-620).
- Does **not** escape `<`, `>` or `&` (unlike `_wrap_hover`).

### `_wrap_label(text, fallback="", width=55, max_lines=2)` (backend/app/services/report_visualizer.py:623)
- For labels that must stay readable in the PNG.
- Truncates to `width*max_lines` (L632-634) and applies the `$`→`&#36;` guard (L635-636).
- Hard-splits words longer than `width` (CJK runs, URLs) (L637-643). Word-wraps (L644-653). If over `max_lines`, keeps the first lines and adds an ellipsis (L654-656). Joins with `<br>`.
- No HTML escaping.

### `_md_cell(text, max_len=80)` (backend/app/services/report_visualizer.py:660)
- `_html_text` followed by `|`→`/`, so the text cannot split a markdown table cell.

### `_node_id(counter, name)` (backend/app/services/report_visualizer.py:665)
- Gives stable Mermaid ids `n0, n1, …` in first-appearance order. Mutates `counter`.

### `_to_float(v)` (backend/app/services/report_visualizer.py:673)
- None → None. bool → None (L683-684). int/float → float, with NaN rejected; `inf` passes (L685-690).
- Strings: takes the first match of `[-+]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)`, then strips commas (L691-698).
- Verified: `"1,808,511"`→1808511.0; `"D+3"`→3.0; `"65%"`→**65.0** (percent is not divided by 100); `True`→None.

### `_explicit_numeric_range(value)` (backend/app/services/report_visualizer.py:703)
- Strips commas, then searches `(-?\d+(?:\.\d+)?)\s*(?:[-–—~]|to)\s*(-?\d+(?:\.\d+)?)` case-insensitively and returns `(min, max)` (L705-714). It is not anchored, so it matches anywhere in the string, including date-like substrings.

### Quant lexicons (backend/app/services/report_visualizer.py:717-797)
- `_QUANT_UNIT_ALIASES` (L717-725): normalizes `% new vehicle sales` variants to `% new car sales`, and `usd/kwh`, `$/kwh` etc. to `USD per kWh`.
- `_AMBIGUOUS_QUANT_UNITS` (L726-730): `%`, `percent`, `units`, `million units`, `count`, `usd million|billion`, `eur …`, `cny …`. These units fail closed.
- `_FORECAST_SIGNAL_RE` (L731-736): forecast|project…|outlook|estimate…|expected|expectation|guidance|scenario|target|revision|revised.
- `_INTERNAL_FORECAST_SOURCE_RE` (L737-742): internal|dossier|synthesis|working assumption/interpolation|analyst interpolation|our case/estimate/forecast|内部推演|本报告|分析师插值.
- `_DENOMINATOR_PATTERNS` (L743-756): 12 (label, regex) pairs: fleet, registrations, deliveries, shipments, production, capacity, revenue, population, households, respondents, gdp, sales.
- `_TIME_BASIS_PATTERNS` (L757-763): ytd, trailing, monthly, quarterly, annual.
- `_MEASURE_FAMILY_PATTERNS` (L764-777): growth, share, price, margin, rate, capacity, production, volume, density, range, emissions, revenue. Order matters; the first match wins.
- `_SUBJECT_STOPWORDS` (L778-788), `_REVISION_NOISE_WORDS` (L789-794), `_GENERIC_SOURCE_FAMILY_WORDS` (L795-797).

### `_canonical_quant_unit(unit)` (backend/app/services/report_visualizer.py:800)
- Collapses whitespace and applies the alias table using a lowercased key. Otherwise returns the raw string, case preserved.

### `_quant_unit_is_comparable(unit)` (backend/app/services/report_visualizer.py:808)
- False for empty, `date`, or ambiguous units (L819-820).
- A unit containing `%` qualifies only if ≥3 characters remain after removing `%` (L821-822). A unit containing ` per `, `/` or ` of ` qualifies (L823-824). Otherwise only a physical whitelist qualifies: `[kmgt]?wh`, `wh/kg`, `kg`, `tonnes`, `barrels`, `credits`, `bps`, `basis points` (L825-828).
- Verified: `%`→F, `% new car sales`→T, `USD billion`→F, `USD/kWh`→T, `GWh`→T, `units`→F, `kg`→T, `%/yr`→**T**.

### `_parse_quant_date(value)` (backend/app/services/report_visualizer.py:831)
- Finds the first `\d{4}-\d{2}-\d{2}` anywhere in the string and parses it with `date.fromisoformat`. Returns None otherwise.

### `_metric_row_period_end(row)` (backend/app/services/report_visualizer.py:841)
- Candidates, in order: `period_end`, `target_date`, then `period.period_end` / `period.end` when `period` is a dict (L843-849). A string `period` is ignored.
- A full 19xx/20xx date is returned as is (L854-860). A bare year becomes **Dec 31** of that year (L861-863).

### `_metric_row_is_publishable(row, kind=None)` (backend/app/services/report_visualizer.py:867)
- The provenance floor, described as "the same as the research forecast renderer" (L869).
- Every row needs a non-empty `source` (falling back to `analyst`), a non-empty `definition`, and an ISO date in `as_of_date` (L875-884).
- `kind` defaults to `_metric_row_kind(row)` (L885). Non-forecast rows are publishable at that point (L886-887).
- Forecast rows also need `source_url` with an `http`/`https` scheme and a netloc (L888-891), and source plus definition must not match `_INTERNAL_FORECAST_SOURCE_RE` (L892-893).

### `_quant_is_projection(row)` (backend/app/services/report_visualizer.py:896)
- Checks, in order:
  - A bool `is_projection` (L897-899).
  - A bool `is_actual`, negated (L900-902).
  - `value_type`, `observation_type`, `fact_type`, `status` labels: actual/historical/observed/reported → False; forecast/forecasted/projection/projected/target/expected → True (L903-908).
  - Otherwise, `_FORECAST_SIGNAL_RE` on metric plus definition (L909-910).
- **Note:** it ignores `value_kind`, which `_metric_row_kind` gives top priority (L1330).

### `_unit_denominator_key`, `_quant_denominator_key` (backend/app/services/report_visualizer.py:913-939)
- `_unit_denominator_key` (L913-924):
  - A unit containing "margin" → `revenue`.
  - Otherwise the first `_DENOMINATOR_PATTERNS` label found in the unit.
  - Otherwise the text after the last ` per ` or `/`, normalized.
  - Otherwise the lowercased unit.
- `_quant_denominator_key(unit, definition)` (L927-939):
  - A non-% unit returns the unit key.
  - For a % unit, it collects the denominator markers found in the definition. With none it returns the unit key. If the set equals `{unit_key}` it returns the unit key. Otherwise it returns **None**, and the row is dropped (L1091-1093).

### `_quant_time_basis(row, metric, definition)` (backend/app/services/report_visualizer.py:942)
- Builds explicit basis tokens from a `period` dict (`period_start`, `period_end`, `start`, `end`, `frequency`, `label`), a string `period`, or the row's own `period_start`, `period_end`, `frequency`, `time_basis`. The tokens are joined with `|` and casefolded (L943-955).
- Otherwise uses keyword labels from `_TIME_BASIS_PATTERNS` joined with `+`, or `"as-of"` (L956-958).

### `_quant_measure_family`, `_quant_subject_tokens` (backend/app/services/report_visualizer.py:961-981)
- `_quant_measure_family`: the first `_MEASURE_FAMILY_PATTERNS` match, or else the normalized definition (L961-966).
- `_quant_subject_tokens`: casefolds the text, maps BEV/PHEV/NEV/ZEV/"electric vehicle(s)/car(s)" to `ev` (L971-972), and drops stopwords and 20xx years (L973-976). If nothing is left, the fallback token is `definition:<normalized definition without years>` (L979-981).

### `_split_quant_families(rows)` (backend/app/services/report_visualizer.py:984)
- Greedy first-fit. A row joins the first family whose running subject intersection overlaps its `_subjects`, and the family's `common` set shrinks to that intersection (L986-995). Only families with ≥2 rows are returned (L996).
- Order-dependent: rows are visited in input order.

### `_source_outlook_family(source)` (backend/app/services/report_visualizer.py:999)
- Builds a publisher/outlook identity:
  - Casefolds, drops possessive `'s` and bracketed citations `[...]` / `【…】` (L1000-1002).
  - Maps BloombergNEF variants to `bnef` (L1003-1007), "electric vehicle outlook" to `evo` (L1008), and `gevo` to "global ev outlook" (L1009). Removes years and noise words (L1010-1015).
  - Returns `""` if no tokens remain or all are generic (report/outlook/forecast…) (L1016-1017).
- Verified: "BloombergNEF Electric Vehicle Outlook 2024"→`bnef evo`; "IEA GEVO 2023"→`iea global ev outlook`; "Report 2024"→`''`.

### `_revision_target_year(name, definition, vintage)` (backend/app/services/report_visualizer.py:1021)
- Collects the 20xx years in name plus definition, discards the vintage year, and returns the year only if exactly one remains.

### `_revision_identity_text(text, *, publisher_family, vintage, target_year)` (backend/app/services/report_visualizer.py:1027)
- Casefolds, normalizes BNEF and "electric vehicle(s)"→`ev`, and cuts at the first post/after/following/due to/because of/in response to (L1034-1045).
- Removes the vintage and target years (L1046), then revision-noise words and publisher tokens (L1047-1051). Returns the remaining tokens joined by spaces.

### `_prepare_quantitative_panels(quantitative, *, max_panels=3, max_rows=10)` (backend/app/services/report_visualizer.py:1055)
- **Input:** a list of quant rows (dicts). Non-lists give `[]` (L1068-1069).
- **Per-row filters** (L1071-1098), in this order:
  1. Non-empty `metric`, and a value via `_metric_row_value`.
  2. A comparable unit.
  3. Non-empty `source` and `definition`, and an ISO `as_of_date`.
  4. Projection flag from `_quant_is_projection`; then `_metric_row_is_publishable(q, "forecast" if projection else "actual")`.
  5. Observed rows (not projections) with negative `staleness_days` are dropped (L1088-1090).
  6. A denominator key; if it is None the row is dropped.
  7. Time basis, measure family and subject tokens, each required to be non-empty.
- **Grouping key** (L1100): `(unit.casefold(), as_of ISO, time_basis, denominator, measure_family)`. Each row record holds metric, value, display_value (`str(value)`, falling back to the float), unit, as_of, source, definition, tier (default `S3`), stale (`is_stale`), projection, `_subjects`, and idx (L1101-1114).
- Each group is split into subject families (≥2 rows). Eligible families are sorted by `(-len, key)` and the first `max_panels` are kept (L1116-1121).
- Rows within a panel are sorted by tier rank, then non-stale first, then observed first, then input index, and truncated to `max_rows` (L1122-1131). `_`-prefixed fields are dropped.
- **Output:** `[{unit, as_of, time_basis, rows:[...]}]` (L1132-1138).
- **Consumer:** part 2's `build_quantitative_dots_html` (L3989). It applies the density gate and writes a markdown-table fallback (L3994-4024).

### `_METRIC_TIME_KEYS`, `_parse_metric_point_time(row)` (backend/app/services/report_visualizer.py:1141-1174)
- Uses `_metric_row_period_end` first (L1151-1153).
- Then scans `period_end`, `target_date`, `period`, `period_start`, `as_of_date`, `as_of`, `date` (L1141-1144). A dict `period` is resolved through its end/start/label sub-keys (L1156-1158).
- Accepts `YYYY-MM-DD` (L1162-1167), `YYYY-MM` → first of month (L1168-1170), and any 19xx/20xx year → **Jan 1** (L1171-1173).
- Verified: `{"period_end":"2030"}`→2030-12-31 but `{"as_of":"2030"}`→2030-01-01, and `{"period_end":"2030-06"}`→2030-12-31. Year snapping therefore depends on which key holds the year (see Surprises).

### `_metric_series_name(metric)` (backend/app/services/report_visualizer.py:1177)
- Strips `(by )?19xx/20xx`, Q1-4/H1-2/FY, and actual/observed/reported/forecast/projected/target/estimate/guidance/plan words, then trims punctuation. If nothing remains it returns the original (L1182-1188).
- Verified: "Tesla Optimus 2026 target"→"Tesla Optimus".

### `_prepare_metric_trajectories(quantitative, *, max_series=8)` (backend/app/services/report_visualizer.py:1191)
- Legacy path. A row qualifies with metric, value, a parseable time and a publishable row (kind from `_metric_row_kind`) (L1204-1211).
- Series key is `(folded name casefold, unit casefold)`. Unit defaults to "value" for display (L1212-1217).
- **Within a series the first row seen for a date wins** (L1219-1220). Point fields: date, value, display_value, metric, source, definition, stale, projection = `kind=="forecast"` (L1221-1230).
- Series with fewer than 2 points are dropped (L1234-1235). Points are sorted by date. Series are sorted by `(-n_points, metric, unit)` and the first `max_series` are kept (L1239-1242).

### DRF2 field readers (backend/app/services/report_visualizer.py:1245-1339)
- The comment block (L1245-1254) documents "new field first, old field fallback" for region/year/value_num/value_kind. A row with no `metric_family` counts as legacy data.
- `_metric_row_family` (L1255-1260): non-empty `metric_family` string with whitespace collapsed, else None.
- `_metric_row_region` (L1263-1269): `region`, falling back to `geography`.
- `_metric_row_technology` (L1272-1277) and `_metric_row_analyst` (L1280-1285): non-empty strings, else None.
- `_metric_row_year` (L1288-1309):
  - An explicit int/float `year` in [1900, 2100], with bools rejected (L1291-1297).
  - Else `_metric_row_period_end(row).year` (L1298-1300).
  - Else the first 19xx/20xx found in `period_start`, `as_of_date`, `date`, `as_of` (L1301-1308).
  - A string `period` is never consulted. Verified: `{"period":"FY2030"}`→None.
- `_metric_row_value` (L1312-1324): **an explicit numeric range in `value` (midpoint) wins over `value_num`** (L1314-1316). Then a finite `value_num` (L1317-1323). Then `_to_float(value)` (L1324).
- `_metric_row_kind` (L1327-1339): `value_kind` or `value_type` strings mapped to actual/forecast (the forecast list includes estimate/estimated). Otherwise `_quant_is_projection`.

### `_aggregate_metric_points(rows)` (backend/app/services/report_visualizer.py:1342)
- Buckets rows by `year`. For each year in ascending order, uses the mean of the actual rows if any exist (kind=actual), else the mean of all rows (kind=forecast) (L1349-1353).
- Point fields: `x=year`, `x_label`, `period_end` (the first chosen row's, or `YYYY-12-31`), `value`, `kind`, `stale` (any chosen row), `n` (all rows that year), `rep` (the first chosen row) (L1354-1363).

### `_build_metric_trajectory_lines(rows, split)` (backend/app/services/report_visualizer.py:1367)
- With a `split` dimension, makes one line per non-empty split value, sorted by name. **Rows that lack the split value are dropped** (L1376-1377). Without a split, makes one unnamed line (L1383-1386).

### `_prepare_metric_family_trajectories(quantitative, *, max_families=8)` (backend/app/services/report_visualizer.py:1390)
- Rows need `metric_family`, a year, a value and publishability (L1402-1411).
- Bucket key is `(family casefold, unit casefold)`; unit defaults to "value" (L1405, L1412-1416).
- Row record: year, value, kind, period_end, region, technology, analyst, stale, metric, display_value, source, definition (L1417-1434).
- A family needs **≥2 distinct years** (L1438-1439). The split is the first of region/technology/analyst with ≥2 distinct non-empty values (L1440-1444).
- Panel: `{title: "{family} · {unit}" + "  (by {split})", unit, split, lines}` (L1448-1454). Panels are sorted by `(-total points, title)` and the first `max_families` are kept (L1455-1456).

### `_legacy_metric_trajectory_panels`, `_metric_trajectory_panels` (backend/app/services/report_visualizer.py:1459-1499)
- The legacy adapter turns each `_prepare_metric_trajectories` series into a single-line panel. `x` is a `date`, `x_label` is its ISO string, `n=1`, and `rep` holds metric/display_value/source/definition. There is no `period_end` key (L1463-1486).
- `_metric_trajectory_panels`: if any row has `metric_family`, it tries the family path. If that returns panels it uses them; otherwise, or if no row has `metric_family`, it uses the legacy path (L1493-1499).
- Consumer: `build_metric_trajectories_html` (L3801).

### `_prepare_technology_shares(quantitative, *, max_families=4)` (backend/app/services/report_visualizer.py:1502)
- Rows need family, technology, year, value and publishability (L1513-1520).
- Per (family, unit), picks the **latest year with ≥2 technologies** (L1541-1547). Each technology's value is the plain mean over all its rows, with **no actual-over-forecast preference** (L1549-1552).
- `share = value / sum(values)`, with the sum defaulting to 1.0 (L1553-1555).
- Output `{family, unit, year, techs:[{tech, value, n, rep, share}]}`. Sorted by `(-n_techs, family)` and capped at 4 (L1556-1563).
- Consumer: part 2 (L3887), which labels bars with `share` as a percentage (L3905).

### `_prepare_regional_comparison(quantitative, *, max_families=4)` (backend/app/services/report_visualizer.py:1566)
- Same structure as technology shares, keyed by region (with `geography` fallback). Picks the latest year with ≥2 regions.
- **Prefers actual rows** for each region's mean and records `kind` (L1614-1623). Output `{family, unit, year, regions:[{region, value, kind, n, rep}]}`. Sorted and capped at 4 (L1624-1631).

### `_prepare_forecast_revision_series(quantitative, *, max_series=3)` (backend/app/services/report_visualizer.py:1634)
- **Row eligibility** (L1650-1676):
  - The metric must end in `(YYYY)` (L1654-1656).
  - Metric plus definition must contain a forecast-signal word (L1657-1659).
  - It needs a value, unit, source, definition and ISO as_of_date, and must be publishable as a **forecast**, which requires an http(s) `source_url` (L1660-1668).
  - The vintage `(YYYY)` must equal the `as_of_date` year (L1669-1671).
  - Publisher family must be non-empty and the target year unambiguous (L1672-1676).
  - Both identity texts must be non-empty (L1677-1690).
- **Key** (L1691-1697): `(publisher_family, target_year, unit casefold, metric_family_text, definition_family_text)`.
- **Per vintage** it keeps the best tier; ties keep the first (L1714-1718).
- A series needs **≥3 vintages** (L1723). Sorted by `(-n, name.lower())`, capped at 3 (L1731-1732).
- Output: `{name, unit, publisher_family, target_year, points:[{vintage, value, display_value, as_of, source, tier, stale}]}`.

### `_REL_LABEL_EN`, `_SIGN_TOKEN`, `_sign_of(rel)` (backend/app/services/report_visualizer.py:1735-1765)
- `_REL_LABEL_EN` (L1736-1742): relation type → English edge label. Unknown types pass through as written by the caller.
- `_SIGN_TOKEN` (L1745-1749): +/positive/supportive/ally/allied → `+`; -/negative/adversarial/rival/oppose → `−` (U+2212); 0/neutral/mixed/transactional → `±`.
- `_sign_of` (L1752-1765): checks `sign`, `valence`, `polarity_label` against the token table, then numeric `polarity` (> 0.15 `+`, < -0.15 `−`, else `±`), else `""`. Verified: `{"sign":0}`→`""`, because the value goes through `str(... or "")` and numeric 0 is falsy.

### `class ReportVisualizer` (backend/app/services/report_visualizer.py:1768)
- Class docstring (L1769-1777): typical use is `ReportVisualizer().build_all(report_id, report_dir, artifacts)`. It never blocks the report.
- **`__init__` (L1779-1788)** holds PNG batch state:
  - `_png_jobs` list of `(fig, abs_path, rel_path, item_id)`.
  - `_png_done` mapping item_id → rel png path.
  - `_batch_mode = False`, `_kaleido_failed = False`.
  - `_skip_notes` mapping item_id → `{reason, fallback_path}`, which `build_all._attempt` consumes (L4382).
  - `build_all` resets all of these (L4350-4354).

### (A) Mermaid helpers (backend/app/services/report_visualizer.py:1790-1956)
All four are `@staticmethod`, return a ```` ```mermaid ```` fenced string, and wrap their bodies in `try/except` that returns `""`. **Production code does not call any of them** (grep: only `backend/tests/test_report_visualizer.py:305-400`). `build_all` does not emit Mermaid (L6-7).

- **`render_mermaid_timeline(timeline, title="Event Timeline")` (L1794-1831).**
  - Accepts a list or `{timeline:[...]}` (L1801). Keys: date/日期/when; event/事件/text/label/description (L1808-1810). Event text goes through `_san_label(…, 90)` (L1811).
  - Dated rows are sorted **lexicographically by the raw date string**; undated rows go last in their original order (L1817-1821).
  - Emits `timeline`, `title …`, and `    {period} : {event}`. Undated rows use `(i)` as the period (L1823-1828).
- **`render_mermaid_causal(paths, title="")` (L1833-1872).**
  - Accepts a dict with paths/edges/causal, or a list (L1842-1845). Items are parsed by `_parse_causal_item` (part 2, L4787).
  - Node cap is `REPORT_VIZ_MAX_NODES` (default 40) (L1853). Emits `flowchart LR`, with the title as a `%%` comment on line 2 (L1855-1857). Edge format: `nX["src"] -->|"label"| nY["tgt"]` (L1864-1865).
  - **On reaching the cap with a new node it `break`s**, which ends the whole loop (L1860-1861). Because it can add two new nodes in one edge, the final node count can exceed the cap by one.
- **`render_mermaid_coalition(coalition, title="Coalition Map")` (L1874-1912).**
  - Clusters come from `_normalize_clusters` (L4841). Emits `flowchart TB` with one `subgraph cN["label (count)"]` per cluster (L1888-1897). Members are `mK["name"]`, with a **global** member cap of `REPORT_VIZ_MAX_NODES` (L1899-1906).
  - The count in the subgraph label is the pre-cap member count (L1896).
- **`render_mermaid_actor_network(actors, title=…)` (L1914-1956).**
  - Accepts a dict with relationships/relations/edges, or a list (L1922-1925). Endpoints use source/from/源 and target/to/目标 (L1935-1936).
  - The label is the English relation label (or `REL`), plus the sign symbol (L1941-1945).
  - Over the node cap it **`continue`s**, skipping only that edge, unlike `causal`'s `break` (L1939-1940).

### (B) matplotlib family plumbing (backend/app/services/report_visualizer.py:1958-1995)
- `_chart_ok()` (L1962-1963): `MATPLOTLIB_AVAILABLE and bool(_cfg("REPORT_VIZ_CHARTS", True))`.
- `_price_hist_ok()` (L1965-1974): uses `Config.REPORT_VIZ_PRICE_HISTORY` if defined (it is not in `backend/app/config.py`). Otherwise reads the env var: unset → True; set → only `"true"` (case-insensitive) enables it (L1970-1973).
- `_dpi()` (L1976-1980): `max(72, int(REPORT_VIZ_DPI or 160))`, with 160 on parse error.
- **`_save(fig, charts_dir, filename)` (L1982-1995).**
  - `os.makedirs(charts_dir)`, then `fig.savefig(path, dpi=_dpi(), bbox_inches="tight")`. This is **not atomic** (no tmp file and rename).
  - **Returns `os.path.join("charts", filename)` regardless of the actual `charts_dir`.** Returns None on any exception and always closes the figure in `finally`.

### `build_scenario_bars(forecast, charts_dir, ensemble=None)` (backend/app/services/report_visualizer.py:1997)
- **Inputs:** forecast.json (dict with `scenarios`, or a list) and an optional ensemble_forecast.json.
- **Steps:**
  - Rows come from `_extract_scenario_rows` (part 2, L5025). Canonical forecast scenarios win; matching ensemble rows contribute only min/max intervals; the result is sorted by `-p` and capped at 14 (L5158-5159). Ensemble-only distributions are rejected unless they sum to 0.95-1.05 (L5155-5157).
  - Each row: name via `_mpl_text(..., "Scenario i", 48)` (L2018). If `hi > lo` it adds asymmetric x-error and records `interval_source` (L2021-2029).
- **Rendering:**
  - Horizontal bars in `#3b6fb0` (L2039). One `errorbar` call per interval source in `_SCENARIO_INTERVAL_ORDER` (ensemble, declared, self_consistency), each with its own color/marker/capsize/legend label from `_SCENARIO_INTERVAL_STYLES` (L2040-2060; styles at L4942-4966).
  - x-limit is `[0, max(1, 1.15·max p)]` (L2064). The title comes from `_scenario_interval_title` (L2065-2066; L4986). The subtitle comes from `_scenario_interval_subtitle`, which can say "point estimates only — no interval data supplied" (L2068-2071; L4998-5022).
  - A legend appears only if some interval exists (L2072-2073). Percent labels sit beyond the upper error bar (L2074-2076).
- **Output:** `charts/scenario_probabilities.png` (L2079). Errors are logged at debug and return None (L2080-2082).

### `build_model_vs_market(forecast, charts_dir)` (backend/app/services/report_visualizer.py:2086)
- **Inputs:** `forecast["binary_forecasts"]`, or a list (L2095). Only items with a `market_anchor` dict are used (L2104-2106).
  - Model p is `_to_float(bf.probability)`. Market p is `anchor.implied_yes_prob`, falling back to `implied_prob` (L2107-2110).
  - Label is the first of `id`, `statement`, `market_id`, `anchor.market_id`, else `F{n}`, at 46 chars (L2113-2114).
  - **No range check:** `"65%"` would be plotted as 65.
- **Density gate:** fewer than `_MODEL_VS_MARKET_MIN_ANCHORED` (3) anchored items returns None (L2120-2123). The static path writes no markdown fallback; the plotly builder does that (L2120-2121 comment).
- **Rendering:** a grey connector per row, market dots `#c0603a` and model dots `#3b6fb0`. xlim [0, 1]. Title "Model vs Market (binary forecasts)" (L2131-2141).
- **Output:** `charts/model_vs_market.png` (L2143). Exceptions are swallowed silently (no log) (L2144-2145).

### `build_worldstate_area(trajectory, charts_dir)` (backend/app/services/report_visualizer.py:2149)
- **Input:** `world_state_trajectory.json` as `{trajectory:[...]}` or a list. Fewer than 2 rows returns None (L2160-2162).
- Per row: a `shares` dict is required. x = `round` via `_to_float`, else the row index (L2173-2175). Shares are parsed with `_to_float`, and names are collected in first-seen order (L2176-2185). The date comes from `_trajectory_row_date` (part 2, L5235): `as_of` or `period_end`, strict ISO.
- **Calendar mode:** used only if **every** snapshot has a date; otherwise the x-axis is "Forecast update step" (L2189-2191, L2202-2210). Missing shares become 0.0 (L2192).
- The CJK check runs on legend labels (≤40 chars, fallback "Series i") (L2194-2200).
- **Rendering:** `stackplot` with alpha 0.85 (L2201). Date axes use AutoDateLocator (3-8 ticks) and ConciseDateFormatter (L2203-2208). ylim is `[0, max(1, max column sum)]` (L2214). Title "Forecast Outcome-Share Trajectory".
- Rows are **not sorted by x**.
- **Output:** `charts/worldstate_trajectory.png` (L2219). Exceptions are swallowed silently.

### `build_timeline_lanes(timeline, charts_dir)` (backend/app/services/report_visualizer.py:2225)
- **Input:** `timeline.json` as a list or `{timeline:[...]}` (L2237-2239). Events come from `_prepare_timeline_events` (part 2, L5292):
  - Key aliases are handled.
  - Flexible dates are parsed by `_parse_flex_date` (L5179). Month and year dates become **midpoints**: a bare year becomes YYYY-06-15 and a quarter its midpoint.
  - Same-day near-duplicates are removed (Jaccard ≥0.55).
  - Score is 1 if the text has digits or currency, plus `len/160` capped at 1.
  - Capped at `REPORT_VIZ_TIMELINE_MAX_EVENTS` (40), keeping the highest scores (L5325-5327).
  - Lane category comes from `_TL_CATEGORIES` keyword precedence: Policy & Regulation, Geopolitics, Consumer & Adoption, Supply Chain & Economics, Companies & Technology, else Other (L5259-5289).
- **Lanes:** only categories that occur, in fixed precedence order (L2244-2247). Labels come from `_timeline_label_plan` (top 12) (L2248). The CJK check covers planned labels only (L2249-2253).
- **Figure:** 2 rows (timeline plus a key panel), width 11 in (L2258-2266).
  - Per-lane dots are jittered ±0.12 cyclically (L2275-2276) and colored `_PALETTE[lane precedence index % 8]` (L2277).
  - Numbered circle annotations sit at the planned offsets (L2288-2306).
  - x margins are ±15 days for a single date, else max(7 days, 4% of span) (L2308-2315). Date locator 3-8 ticks; y-axis inverted with the first lane at top (L2316-2321).
  - The key panel lists `NN  YYYY-MM-DD  label` in 1 column, or 2 if there are more than 6 labels (L2330-2348). **The key prints `event["dt"]`**, the parsed midpoint, not the original precision label.
- **Output:** `charts/timeline_lanes.png` (L2350). Errors are logged at debug.

### `build_actor_network(actors, charts_dir, graph_priors=None)` (backend/app/services/report_visualizer.py:2357)
- **Input:** an actors dict with `relationships`/`relations`/`edges` plus an `actors` list (for aliases and `role_class`), or a bare relationship list (L2369-2373). `graph_priors` is a dict `{entity: weight}` (L2375-2380).
- **Canonicalization:** `_canonical_actor_map` / `_canonicalize` (part 2, L5337-5375): exact name or alias match first, then a substring match (≥4 chars) that picks the longest canonical name.
- **Edges** (L2382-2408): endpoints via source/from and target/to only (no 源/目标 aliases, unlike the Mermaid helper). Self-loops are dropped. Edges are deduped on `(source, target, TYPE)`, and the sign defaults to `±` (L2403). Degree and first-seen order are tracked.
- **Node cap:** `REPORT_VIZ_NETWORK_MAX_NODES` (default 60, minimum 2). Nodes are ranked by `(-prior, -degree, first_seen)` and edges are restricted to kept nodes. Fewer than 2 nodes or no edges returns None (L2412-2426).
- **Layout:** `_network_layout` (L5378): networkx `spring_layout(seed=7, k=0.9/√n, iterations=60)`, or deterministic concentric rings ordered by degree.
- **Weights:** priors if **any** kept node has a prior, else degree (L2435-2440).
  - Role-class colors are assigned from the sorted unique `role_class` values ("other" by default) to `_PALETTE` (L2442-2449).
  - Labels come from `_actor_label_plan` (top 22) (L2450). The CJK check covers labels plus class names (L2451-2457).
- **Drawing:**
  - `FancyArrowPatch` edges colored by sign (+ green, − red, ± grey), alpha 0.48, with arc rad cycling −0.035/0/0.035 (L2465-2480).
  - Node scatter sized `260 + 900·w/wmax` (L2482-2497). Annotations use leader lines (L2499-2519).
  - The legend combines role classes and the three edge signs, placed below the plot (L2521-2535). Limits include the label boxes, with equal aspect and axes hidden (L2538-2549).
- **Output:** `charts/actor_network.png` (L2551).

### `build_comparison_bars(comparison, charts_dir)` (backend/app/services/report_visualizer.py:2558)
- **Input:** `comparison.json` `dimensions[]` or a list (L2566-2568). The producer is `report_agent._scenario_diff_structured` (`backend/app/services/report_agent.py:9318-9372`), which writes `{name, baseline:"12.3%", scenario:"…%", delta, verdict}`. It is written to `comparison.json` at `backend/app/services/report_agent.py:11383-11389` when `REPORT_COMPARISON_TABLE` is on.
- Dimensions where both baseline and scenario parse with `_to_float` are kept. Labels use name/dimension, fallback "Dim n", 30 chars (L2572-2582).
- **Rendering:** grouped bars (width 0.38, Baseline `#9aa5b1`, Scenario `#3b6fb0`) with rotated tick labels. y-label "Value". Title "Baseline vs Scenario (comparison)" (L2590-2602). Imports `numpy` lazily (L2590).
- **Output:** `charts/comparison_bars.png` (L2604).

### `build_calibration_curve(calibration, charts_dir)` (backend/app/services/report_visualizer.py:2610)
- **Input:** `{bins:[...]}` or a list. Per bin, x is the first float of `mean_predicted`/`mean_pred`/`pred` and y the first float of `observed`/`hit_rate`/`smoothed_hit_rate`/`empirical` (via `_first_float`, L4869) (L2619-2632).
- Points are sorted by x (L2635-2637). Plots the dashed diagonal "Perfect calibration" and the observed line, with axes [0, 1]² at equal aspect (L2638-2648). A single valid bin is enough; there is no weighting by bin count and no clamping.
- **Output:** `charts/calibration_curve.png` (L2650).
- **No production caller supplies `artifacts["calibration"]`** (see Surprises).

### `render_market_price_history(price_history, anchors, out_dir)` (backend/app/services/report_visualizer.py:2656)
- **Inputs:** `price_history` is `{market_id: [{t: unix_seconds, p: 0..1}, ...]}` (docstring L2665). `anchors` is `forecast["binary_forecasts"]` (L4612-4613), or flattened anchor dicts.
- Normalization (`_normalize_price_anchors`, part 2, L4881-4935):
  - Keeps anchors whose `market_id` appears in `price_history` with ≥2 valid points, deduped by market_id in first-seen order.
  - Converts with `datetime.utcfromtimestamp`, clamps p to [0, 1] and sorts by time.
  - model_p is probability/model_prob/model_p/p. market_p is implied_yes_prob/implied_prob, else the last history point. divergence is `anchor.divergence`, else model − market. label is `_mpl_text(id|statement|label|market_id, 52)`.
- Caps at `REPORT_VIZ_MAX_NODES` (40), keeping the first seen (L2682-2684). The CJK check covers all labels together; one uncovered label skips the whole family (L2685-2689).
- **Grouping:** **2 subplots per figure if there are more than 6 anchors, else 1** (L2691-2692).
- Each axis shows the market line (`#c0603a`, markers), a dashed model `axhline` labeled `Model P(yes) = NN%`, and a divergence box "Divergence (model − market): ±NN pp". ylim [0, 1], date format `%Y-%m-%d` (L2698-2721). `autofmt_xdate` (L2723).
- **Output:** `charts/market_price_history_{gi}.png` for gi = 1..ceil(n/per_fig) (L2725-2727). Returns the list of relative paths.
- **Any exception returns `[]`, discarding paths already saved; the PNG files stay on disk** (L2729-2730).

### Plotly family header (backend/app/services/report_visualizer.py:2734-2740)
- Comment only. It states that each HTML references a shared same-directory `plotly.min.js` via `include_plotlyjs='directory'`, falling back to inline, and that data extraction mirrors the matplotlib builders. The methods themselves start at L2742 (part 2).

---

## Control flow

1. **Report generation.** `ReportAgent.generate_report` (`backend/app/services/report_agent.py:11113`) calls `_inject_visualizations` when `Config.REPORT_VISUALIZATIONS` is on (`backend/app/services/report_agent.py:11517-11521`). That calls `_collect_viz_artifacts` (`backend/app/services/report_agent.py:8926-8999`), then `ReportVisualizer().build_all(...)` (`backend/app/services/report_agent.py:8899-8906`).
2. **`build_all` (part 2, L4313).**
   - Returns `[]` if `REPORT_VISUALIZER` is off (L4344-4345).
   - Resets batch state (L4350-4354). Resolves graph priors, falling back to structural priors (L4359-4361).
   - Runs the **plotly** builders through `_attempt` (L4364-4391). Those builders call this slice's helpers: `_apply_layout`, `_wrap_*`, `_html_text`, `_md_cell`, `_timeline_label_plan`, `_actor_label_plan`, and the `_prepare_*` functions (grep anchors L2999, L3361, L3561, L3801, L3887, L3934, L3989, L4097).
   - The actor network is attempted only if `_meta_charts_on()` (L4417-4426).
   - Flushes the kaleido PNG jobs and attaches `png_path` (L4525-4529).
3. **`_run_matplotlib_family` (part 2, L4547).**
   - Skips the whole family if `_chart_ok()` is False (L4557-4560).
   - `_fallback` (L4564-4582) calls a slice builder **only if the matching plotly item has no `png_path`**. If the plotly item exists, the matplotlib PNG is attached as its `png_path`; otherwise it becomes a standalone `type:"png"` item. The fallbacks run in this order:
     1. `build_scenario_bars` (L4584-4587).
     2. `build_model_vs_market` (L4588-4590).
     3. `build_timeline_lanes` (L4591-4593).
     4. `build_actor_network`, only if `_meta_charts_on()` (L4596-4601).
     5. `build_worldstate_area` (L4602-4605).
   - `render_market_price_history` runs if any price-history item lacks a PNG, or there are none, and `_price_hist_ok()` (L4608-4630). Each returned file is matched **by stem** to the plotly item `market_price_history_{n}`.
   - `build_comparison_bars` runs when `artifacts["comparison"]` is truthy (L4633-4646). `build_calibration_curve` runs when `artifacts["calibration"]` is truthy (L4647-4660). Otherwise `skipped` gets `no_input` or `empty_after_parse`.
4. `_persist_manifest` atomically writes `viz_manifest.json` (L4681-4703). Then an INFO summary is logged (L4540-4544).
5. **Translation path.** After a translation, `report_agent` calls `localize_chart_alt_text(translated_md, tgt_code)` (`backend/app/services/report_agent.py:7544-7545`).
6. **Offline path.** `backend/scripts/backfill_report_visuals.py:503` calls `build_all` with artifacts from `_artifacts` (`backend/scripts/backfill_report_visuals.py:342-364`).
7. **Direct callers (tests only).** The Mermaid helpers and direct builder calls (`backend/tests/test_report_visualizer.py:305-411`, `backend/tests/test_wave9_visualizer.py:353-354`, `backend/tests/test_report_chart_quality.py:278,354-355`).

---

## Data & artifacts

**Files written by this slice** (all through `_save`, L1982-1995; PNGs at `dpi=max(72, REPORT_VIZ_DPI)` with a tight bbox, into `charts_dir`, which in production is `reports/{id}/charts/` (L4347)):

| File | Writer | Notes |
|---|---|---|
| `charts/scenario_probabilities.png` | L2079 | Same filename the kaleido export of the plotly chart uses (stem at L3006). The fallback runs only when that export is missing. |
| `charts/model_vs_market.png` | L2143 | Needs ≥3 anchored binaries. |
| `charts/worldstate_trajectory.png` | L2219 | |
| `charts/timeline_lanes.png` | L2350 | |
| `charts/actor_network.png` | L2551 | Only via build_all when `REPORT_META_CHARTS` is on. |
| `charts/comparison_bars.png` | L2604 | matplotlib-only chart. |
| `charts/calibration_curve.png` | L2650 | matplotlib-only chart; not reachable in production. |
| `charts/market_price_history_{n}.png` | L2725 | `n` numbers **figures (groups)**, not anchors, when there are more than 6 anchors. |

**Files read by this slice:** none directly. `_installed_cjk_fonts` reads installed system font files through matplotlib's `font_manager`/`ft2font` (L438-443).

**Manifest items produced from this slice's outputs** (shape set in part 2, L4578-4582, L4624-4630, L4637-4655): `{id, path:"charts/<file>.png", type:"png", title, caption(=title), source, placement_hint}`, or `png_path` attached to an existing HTML item. The API serves only `charts/…` relative paths (`backend/app/api/report.py:1364-1378`).

**Important in-memory structures:**
- Quant panel, from `_prepare_quantitative_panels` (L1132-1137): `{unit, as_of, time_basis, rows:[{metric, value, display_value, unit, as_of, source, definition, tier, stale, projection, idx}]}`.
- Trajectory panel, from `_prepare_metric_family_trajectories` / legacy (L1448-1454, L1480-1485): `{title, unit, split, lines:[{name, points:[{x, x_label, value, kind, stale, n, rep, (period_end in family path only)}]}]}`.
- Tech-share panel (L1556-1561): `{family, unit, year, techs:[{tech, value, n, rep, share}]}`. Region panel (L1624-1629): `{family, unit, year, regions:[{region, value, kind, n, rep}]}`.
- Revision series (L1724-1730): `{name, unit, publisher_family, target_year, points:[{vintage, value, display_value, as_of, source, tier, stale}]}`.
- Label plans: timeline (L536-546) `{(dt,text):{label, offset, ha, va, bbox, index}}`; actor (L598) `{node:{label, xytext, bbox}}`.
- Batch state on the instance (L1782-1788). Process-global caches and flags: `_MPL_CJK_FONT_CACHE` (L402), `_KALEIDO_RUNTIME_OK` (L186).

**Expected input artifact shapes**, as consumed here:
- `forecast.scenarios[]` with `probability|prob|p`, `p_low/p_high` or `min/max`, `interval_source` (via L5025-5159).
- `forecast.binary_forecasts[]` with `probability`, `market_anchor{implied_yes_prob|implied_prob, market_id, divergence}`, `id`, `statement`.
- world_state_trajectory `{trajectory:[{round, shares:{name:share}, as_of|period_end}]}`.
- timeline `[{date|日期|when, event|事件|text|label|description}]`.
- actors `{actors:[{name, aliases, role_class}], relationships:[{source|from, target|to, type|relation|rel, sign|valence|polarity_label|polarity}]}`.
- comparison `{dimensions:[{name, baseline, scenario}]}`.
- calibration `{bins:[{mean_predicted…, observed…}]}`.
- price history `{market_id:[{t, p}]}`.
- quantitative rows `{metric, value, value_num, unit, source, source_url, definition, as_of_date, period/period_end/target_date, year, metric_family, region|geography, technology, analyst, value_kind|value_type, is_projection, is_actual, tier, is_stale, staleness_days}`.

---

## Config / env knobs

| Knob | Default | Effect | Anchor (read site) | Defined in Config? |
|---|---|---|---|---|
| `REPORT_VISUALIZER` | True | Master switch; when off, `build_all` returns `[]` | L4344 (part 2) | yes, `backend/app/config.py:203` |
| `REPORT_VIZ_CHARTS` | True | Enables the matplotlib family (`_chart_ok`) | L1963 | yes, `backend/app/config.py:208` |
| `REPORT_VIZ_DPI` | 160 (floor 72) | PNG dpi | L1976-1980 | yes, `backend/app/config.py:210` |
| `REPORT_VIZ_MAX_NODES` | 40 | Node cap for the Mermaid causal/coalition/actor helpers; anchor cap for price history | L1853, L1887, L1928, L2682 | yes, `backend/app/config.py:212` |
| `REPORT_VIZ_NETWORK_MAX_NODES` | 60 (min 2 kept) | Static actor-network node cap | L2412, L2422 | yes, `backend/app/config.py:225` |
| `REPORT_VIZ_TIMELINE_MAX_EVENTS` | 40 | Timeline event cap (applies to this slice via `_prepare_timeline_events`) | L5325 (part 2) | yes, `backend/app/config.py:223` |
| `REPORT_VIZ_PRICE_HISTORY` | True | Enables price-history charts; Config attribute first, else env, where only `"true"` enables | L1965-1974 | **no** (only `.env.example:268`) |
| `REPORT_META_CHARTS` | False | Restores actor_network and source_mix charts; truthy strings are `1/true/yes/on` | L211-220 | **no** (also absent from `.env.example`) |
| `REPORT_VIZ_MERMAID` | True | Docstring says it affects library callers (L35). **Never read** | (none) | yes, `backend/app/config.py:205` |
| `REPORT_VIZ_INTERACTIVE` | True | Plotly family switch | L2744 (part 2 boundary) | yes, `backend/app/config.py:217` |
| `REPORT_VIZ_PNG_EXPORT` | True | kaleido PNG export | L2749 (part 2 boundary) | yes, `backend/app/config.py:221` |
| `REPORT_VIZ_PLOTLYJS_INLINE` | False | Forces inline plotly.js; read via `_cfg` (L202-208) at L2806 and L4731 | part 2 | **no**, so the env var is ignored |

Dependency availability also acts as a gate: `MATPLOTLIB_AVAILABLE` (L141-148), `PLOTLY_AVAILABLE` (L156-161), `NETWORKX_AVAILABLE` (L167-172), `KALEIDO_AVAILABLE` (L180-184).

---

## External calls

- **No LLM, HTTP or DB calls anywhere in the slice.** The module docstring says it is LLM-free (L1).
- **Filesystem:** PNG writes (`savefig`, L1987) and `os.makedirs` (L1985). Font file reads (L438-443).
- **Environment:** `os.environ` reads for `REPORT_META_CHARTS` (L217) and `REPORT_VIZ_PRICE_HISTORY` (L1970).
- **Third-party libraries:** matplotlib (Agg backend set at import, L143), `matplotlib.dates` (L2204, L2256, L2690), `matplotlib.lines`/`patches` (L2459-2460), numpy (L2590), and `importlib.util.find_spec("kaleido")` (L182). Kaleido's Chromium subprocess is launched only in part 2 (`fig.write_image`/`pio.write_images`, L2836, L2873).
- **Config import:** `from ..config import Config` lazily inside `_cfg` (L205).

---

## Cross-module edges

**Into this slice:**
- `backend/app/services/report_agent.py:8899-8906` constructs `ReportVisualizer` and calls `build_all` (part 2), which calls this slice's builders through `_run_matplotlib_family` (L4584-4660).
- `backend/app/services/report_agent.py:7544-7545` calls `localize_chart_alt_text`.
- `backend/scripts/backfill_report_visuals.py:35,503` calls `ReportVisualizer().build_all`.
- `frontend/src/utils/vizManifest.js:100-117` mirrors `CHART_TITLES_ZH`; `backend/tests/test_report_zh_presentation.py:46,54` pins the sync.
- `backend/app/api/report.py:1358-1410` serves `viz_manifest.json` items, including the `png_path` values produced here.
- Tests (11 files reference the module): `backend/tests/test_report_visualizer.py`, `test_wave9_visualizer.py`, `test_report_chart_quality.py`, `test_report_visualizer_axes.py`, `test_loop006_static_viz_fallbacks.py`, `test_report_viz_and_pdf.py`, `test_report_zh_presentation.py`, `test_sessionb_forecast_charts.py`, `test_sessionb_viz_signal.py`, `test_viz_manifest_provenance.py`, `test_backfill_report_visuals.py` (all under `backend/tests/`).
- Part 2 of the same file consumes many slice helpers, e.g. `_finalize_plotly_html` / `_plotly_document_title` (L2811), `_apply_layout` (L2999…), `_timeline_label_plan` (L3361), `_actor_label_plan` (L3561), `_metric_trajectory_panels` (L3801), `_prepare_technology_shares` (L3887), `_prepare_regional_comparison` (L3934), `_prepare_quantitative_panels` / `_quant_panel_is_dense` / `_quant_panel_subtitles` (L3989-4031), `_prepare_forecast_revision_series` (L4097).

**Out of this slice:**
- `backend/app/config.py` `Config` via `_cfg` (L205).
- Part-2 helpers in the same file:
  - Scenario: `_extract_scenario_rows` (L5025), `_scenario_interval_title` / `_subtitle` (L4986/L4998), `_SCENARIO_INTERVAL_STYLES` / `_ORDER` (L4942/L4969).
  - Trajectory and timeline: `_trajectory_row_date` (L5235), `_prepare_timeline_events` (L5292), `_TL_CATEGORIES` (L5259).
  - Actors: `_canonical_actor_map` (L5337), `_canonicalize` (L5360), `_norm_key` (L5332), `_network_layout` (L5378).
  - Parsing: `_first_float` (L4869), `_normalize_price_anchors` (L4881), `_parse_causal_item` (L4787), `_normalize_clusters` (L4841).

---

## Invariants, gates, validation

- **Never raise.**
  - Mermaid helpers catch everything and return `""` (L1830-1831, L1871-1872, L1911-1912, L1955-1956).
  - matplotlib builders catch everything and return None, or `[]` for price history (L2080-2082, L2144-2145, L2220-2221, L2351-2353, L2552-2554, L2605-2606, L2651-2652, L2729-2730).
  - `build_all._attempt` adds a second exception guard for plotly builders (L4373-4379).
- **Family gates:** `_chart_ok()` at the start of every matplotlib builder (e.g. L2005, L2091, L2156, L2233, L2365, L2562, L2615, L2673).
- **Glyph-truth gate:** a chart is skipped rather than rendered with tofu boxes or placeholder labels (L376-383, L457-474).
- **Density gates:**
  - Model vs market needs ≥3 anchored items (L255, L2122).
  - Quant panels need ≥4 rows or ≥2 metrics (L256-265, applied in part 2).
  - World-state needs ≥2 snapshots (L2161, L2187).
  - Revisions need ≥3 vintages (L1723). Trajectories need ≥2 points or years (L1234, L1438).
  - Tech and region charts need ≥2 categories in the chosen year (L1543, L1606).
- **Provenance floor:** `_metric_row_is_publishable` is applied in every quant prep function (L1085-1087, L1209-1210, L1409-1411, L1518-1519, L1581-1582, L1667).
- **Unit comparability:** ambiguous units are excluded from same-denominator panels (L726-730, L808-828). Percentage units need a matching denominator in the definition (L927-939).
- **Scenario distribution coherence:** inherited from `_extract_scenario_rows`. Ensemble rows never append to canonical rows, and an ensemble-only distribution must sum to 0.95-1.05 (L5025-5040, L5155-5157).
- **Determinism:** fixed sort keys everywhere (e.g. L1119, L1241, L1455, L1562, L1630, L1731, L2414-2421). Spring layout seed 7 (L5388). The label planners are pure (L496-604).
- **Probability ranges** are validated only in part 2's `_extract_scenario_rows` (0 ≤ p ≤ 1, L5042-5046) and clamped in price-history normalization (L4919). Model/market binary probabilities and calibration bins are **not** range-checked in this slice (L2107-2110, L2627-2628).

---

## Failure modes & recovery

| Condition | Behavior | Anchor |
|---|---|---|
| matplotlib missing or `REPORT_VIZ_CHARTS` off | Every builder returns None/[]; build_all records `matplotlib_family=matplotlib_unavailable_or_disabled` | L1962-1963, L4557-4560 |
| No CJK-capable font for the labels | Chart skipped with an INFO log; build_all records nothing for single-chart fallbacks (the `_fallback` helper silently returns) | L2033-2035, L4573-4574 |
| `savefig` failure (disk or permissions) | `_save` returns None; a partial file may remain because the write is not atomic | L1984-1990 |
| Exception partway through price-history groups | Returns `[]`; earlier PNGs stay on disk but are not attached | L2694-2730 |
| kaleido runtime failure (part 2) | Process-wide `_KALEIDO_RUNTIME_OK=False`; matplotlib fallbacks fill the PNG slots until the process restarts | L186, L2839, L4564-4582 |
| networkx missing | Concentric fallback layout | L5392-5411 |
| Config not importable | `_cfg` returns code defaults | L204-208 |
| Missing optional artifact | build_all records `no_input`; comparison/calibration skip records come from `_run_matplotlib_family` | L4645-4646, L4659-4660 |
| Static builder returns None while a plotly item exists | HTML item keeps no `png_path`; PDF/exec-brief embedding presumably degrades to a link (handled by report_agent, not verified here) | L4573-4576 |

There are no retries anywhere in the slice. All failures degrade.

---

## Surprises

1. **The calibration curve is effectively dead in production.** `build_calibration_curve` (L2610) runs only when `artifacts["calibration"]` is truthy (L4647-4648). Neither collector sets that key: `report_agent._collect_viz_artifacts` (`backend/app/services/report_agent.py:8926-8999`) and `backfill_report_visuals._artifacts` (`backend/scripts/backfill_report_visuals.py:342-364`) both leave it out. So every report records `calibration_curve=no_input`. Docs claim otherwise: module docstring L3-4, `backend/app/config.py:200-202`, and `backend/app/services/forecast_ledger.py:121-123` ("report_visualizer renders calibration curves"). Doc-vs-code drift.

2. **Suspected bug: `_cfg` never reads the environment** (L202-208). `REPORT_VIZ_PLOTLYJS_INLINE` is read only through `_cfg` (L2806, L4731) and is **not** a `Config` attribute (no hit in `backend/app/config.py`). So `.env.example:588`'s documented escape hatch (`REPORT_VIZ_PLOTLYJS_INLINE=true`) has no effect. Two other knobs work around this with their own env fallbacks, and their truthy parsing is inconsistent: `REPORT_META_CHARTS` accepts `1/true/yes/on` (L218-219), while `REPORT_VIZ_PRICE_HISTORY` accepts only `true`, so `=1` disables it (L1973).

3. **`REPORT_VIZ_MERMAID` is dead.** `Config` defines it (`backend/app/config.py:205`) and the docstring says it still affects library callers (L35), but no code reads it. The four Mermaid helpers (L1794-1956) are called only by tests. `.env.example:262-264` and the config comments at `backend/app/config.py:200-207` still describe Mermaid blocks plus matplotlib as the output. The current output is plotly first.

4. **Suspected bug: `$` escaping leaks into static scenario labels.** `_extract_scenario_rows` stores names already passed through `_html_text`, which turns ≥2 `$` into `&#36;` (L5119, L618-619). `build_scenario_bars` then calls `_mpl_text(r["name"])` (L2018), so the PNG shows the literal text `&#36;100B …` (verified: `_mpl_text(_html_text("$100B vs $65B"))` returns `&#36;100B vs &#36;65B`). The reverse happens for price history: `_normalize_price_anchors` labels go through `_mpl_text`, which escapes to `\$` (L4930), and the plotly title then reuses them (L3212), likely showing a backslash.

5. **Suspected bug: range parsing takes precedence over an explicit `value_num`.** `_metric_row_value` checks `_explicit_numeric_range(value)` before `value_num` (L1314-1316), and the range regex is unanchored (L706-708). Verified: `{"value":"37% (2024-2025)","value_num":37}` → **2024.5**; `{"value":"2030-12"}` → **1021.0**. Every quant prep function (L1076, L1206, L1407, L1516, L1579, L1660) inherits this.

6. **Suspected bug: market-price-history PNG pairing mismatch.** Plotly writes one HTML per anchor, `market_price_history_{i}` (L3190, L3218-3219), and kaleido exports the PNG under the same stem (L2849). The matplotlib fallback numbers **groups**, with 2 anchors per figure when there are more than 6 anchors (L2691-2692, L2725). `_run_matplotlib_family` attaches fallback PNGs by stem (L4618-4622). So with more than 6 anchors:
   - Item `market_price_history_1` (anchor 1 only) gets a PNG that shows anchors 1 and 2.
   - Items beyond ceil(n/2) get no PNG.
   - If kaleido succeeded for some anchors and not others (`need_ph` is true when any item lacks a PNG, L4609), the matplotlib run **overwrites** kaleido PNGs that were already attached, because the filenames are identical.

7. **Suspected semantic issue: technology "shares" are computed for any unit.** `_prepare_technology_shares` divides each technology's value by the column sum whatever the unit is (L1553-1555), and part 2 prints it as `NN%` bar text and `NN.N% share` hover text (L3905, L3909-3910). For price or energy-density families (e.g. USD/kWh for LFP vs NMC) the "share" means nothing. It also averages actual and forecast rows together (L1551), while the sibling `_prepare_regional_comparison` prefers actuals (L1614-1616).

8. **Inconsistent projection classification.** `_prepare_quantitative_panels` decides whether to apply the forecast publishability floor (http(s) URL required) using `_quant_is_projection` (L1084-1087), which ignores `value_kind`. Every other prep function uses `_metric_row_kind`, which puts `value_kind` first (L1327-1339). The two disagree on, for example, `value_kind="estimate"` (forecast per L1337) when `value_type`, `observation_type` and the text carry no forecast signal.

9. **Year and date snapping differ by key (doc drift).**
   - `_parse_metric_point_time`'s docstring says year and month granularity map to the first day of the period (L1148-1150). Yet `period_end`/`target_date` bare years map to **Dec 31**, and `period_end:"2030-06"` maps to 2030-12-31 (via `_metric_row_period_end`, L861-863).
   - `_metric_row_year`'s docstring order "period_end→as_of_date→date→period" (L1289-1290) does not match the code (`year` → `period_end`/`target_date`/period-dict → `period_start`/`as_of_date`/`date`/`as_of`), and a **string `period` is never used** (verified `{"period":"FY2030"}`→None). The legacy path does honor a string `period` (L1141-1144).

10. **Static timeline key shows false precision.** The key prints `event_date:%Y-%m-%d` from the parsed `dt` (L2343). `_parse_flex_date` places a bare year at YYYY-06-15 and a quarter at its midpoint (L5210-5215, L5193-5202), so a "2030" event is listed as `2030-06-15`. The event's `precision` and raw `date` fields (L5319-5321) go unused here.

11. **CJK same-day duplicates are never deduped.** `_tokens` is ASCII only (L348), so for Chinese events `_jaccard` is always 0 and the dedupe in `_prepare_timeline_events` (L5313) never fires.

12. **`_save` hard-codes the returned path prefix.** It returns `"charts/<file>"` whatever `charts_dir` is (L1988). This is fine in build_all (L4347) but wrong for any other directory (tests pass `tmp_path/"declared"`, `backend/tests/test_wave9_visualizer.py:353`). On Windows `os.path.join` would produce a backslash, which `safe_chart_path` rejects (`backend/app/api/report.py:1366`).

13. **Mermaid cap semantics differ.** `render_mermaid_causal` `break`s on the node cap and can overshoot by one node (L1860-1863). `render_mermaid_actor_network` `continue`s (L1939-1940). Mermaid timeline dates sort lexicographically (L1820), and `:` in event text is not sanitized (L365-369), even though `:` separates period from events in Mermaid timeline syntax. These matter only for the test-only helpers.

14. **HTML escaping is inconsistent.** `_wrap_hover` escapes `& < >` (L328). `_html_text` and `_wrap_label`, used for plotly axis and tick labels, do not (L612-620, L628-657), so a label such as `<5% of sales` may be parsed as markup by plotly. Suspected, not verified at render time.

15. **Label-planner geometry differs from the renderer.** `_timeline_label_plan` assumes figure height `max(3.8, 1.05·lanes+2.4)` (L513). `build_timeline_lanes` actually draws `max(3.2, 0.9·lanes+2.0)` plus a separate key panel (L2260-2266). The "collision-free" guarantee is therefore approximate.

16. **Unsorted x in the world-state stackplot.** `build_worldstate_area` never sorts snapshots by `round` or date (L2167-2192), so out-of-order trajectory rows would draw folded areas. Suspected; the producer probably emits rows in order.

17. **Title drift between static and manifest.** The static chart's internal titles are "Model vs Market (binary forecasts)" (L2139) and "Baseline vs Scenario (comparison)" (L2600). The matplotlib manifest titles are "Model vs Market" (L4588) and "Baseline vs Scenario" (L4639). Both manifest strings are in `CHART_TITLES_ZH`, but the PNG's baked-in title text stays English in any case.

18. **Silent failures.** `build_model_vs_market`, `build_worldstate_area`, `build_comparison_bars`, `build_calibration_curve` and `render_market_price_history` swallow exceptions with **no log at all** (L2144-2145, L2220-2221, L2605-2606, L2651-2652, L2729-2730). Scenario, timeline and actor builders log at debug. The fallback loop also records no skip reason when a static builder returns None (L4573-4574).

19. **Shared pyplot state.** The builders use the global `plt.subplots` state machine (e.g. L2038). With Flask threads running several reports at once, pyplot is not thread-safe; `_close_matplotlib_figure` avoids `close('all')` (L190) but does not serialize rendering. A risk, not an observed bug.

20. **Minor items.**
    - `_to_float("65%")` returns 65 with no percent scaling (L691-698). Model-vs-market and calibration therefore do not normalize percent strings.
    - `_quant_unit_is_comparable("%/yr")` is True (L821-822).
    - `_sign_of({"sign":0})` returns `""` (L1755).
    - `_prepare_metric_family_trajectories` calls `_metric_row_period_end(q)` twice per row (L1422-1423).
    - The family-path `period_end` point field (L1357, L1421-1425) is not read by the in-file renderer (L3776-3879).
    - Static and plotly actor-network fallbacks resolve graph priors slightly differently: build_all uses structural priors when `graph_priors` is not a non-empty dict (L4359-4361); the fallback uses `graph_priors or graph_priors_structural` (L4600-4601).
    - `_normalize_price_anchors` uses `datetime.utcfromtimestamp`, which is deprecated in Python 3.12+ (L4916).

21. **Docstring drift inside the file.** The module docstring says each HTML has "plotly.js inline, fully offline" (L17-19) and `backend/app/config.py:213-216` says the same. The code uses `include_plotlyjs='directory'` with a shared `plotly.min.js` (L2807), as the slice's own section header states (L2736-2738). `backend/app/services/report_agent.py:8883-8887` and `:11513-11516` still describe outputs as `charts/*.mmd + *.png` with Mermaid placement.
