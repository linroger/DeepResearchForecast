---
name: data-visuals
description: Use this skill when research or forecast reports rely on official statistical series retrieved with data tools and stored under data/datasets.json. Render deterministic charts with exact units, missing gaps, distinct observation statuses, fiscal periods and citable source captions. Use the bundled renderer for history, publisher projections and comparable series; never invent or transcribe observations.
---

# Data Visuals

When the runtime injects this body it is complete; do not read `SKILL.md` again.
Read [references/chart-patterns.md](references/chart-patterns.md) only for a
chart-selection, forecast-overlay or visual-QA decision.

## 1. Chart only what the argument needs

A chart earns its place when the reader needs the series' **shape**: a trend, a
turning point, the distance to a forecast threshold, or the gap between
economies. Write its one message first ("unemployment has risen for six months
while payroll growth slowed"). One chart, one message. When a single latest
value carries the point, quote it with its `[S#]` instead of charting it.

Every mark comes from the immutable series file named by `data/datasets.json`
(for example, `data/<slug>.<hash>.json`). Never chart numbers you typed, copied
from a web page, or estimated yourself. Publisher estimates and projections
retain their explicit labels; never splice incompatible definitions into one line.

## 2. Chart grammar

The renderer applies these rules; follow them in any figure you describe.

- One line per series on a native date axis. Missing periods break the line;
  never interpolate or smooth them away.
- Mark and label only the latest observed value (never an estimate, partial
  period, projection or value without status).
- Each point keeps the status the data tools stored (`observed`, `unknown`,
  `preliminary`, `estimate`, `partial`, `projection`): observed = solid line;
  status not supplied = light solid line; preliminary = dotted with triangles;
  estimate = dash-dot with squares; partial period (a month or fiscal year
  still open) = dotted with a hollow marker; publisher projection = dashed over
  a shaded band, named with its publisher (IMF WEO, World Bank GEP). A step
  between two statuses takes the less certain style. BLS `P` means
  preliminary; an ambiguous `P` from another source stays unknown.
- WEO/GEP rows carry vintage-based status from the data tools (projection
  from the vintage year, estimate the year before). Never infer a boundary
  from the current year or draw your own trend extrapolation.
- Use keyed fiscal period labels such as `FY2025` from `provenance.periods`.
  Label partial coverage; never display the calendar start year as the fiscal
  year or compare partial and complete annual aggregates as equivalent.
- Title = the series label used across the report (curated title, the
  geography when the title lacks it, the transform). y-axis label = units
  exactly as published (index base, chained-dollar year, percent vs percentage
  points); `--lang zh` translates common units and keeps any other verbatim.
  The subtitle states frequency (unless the title names it), seasonal
  adjustment (SA, NSA, SAAR) and daily-to-monthly aggregation. Do not mix SA
  and NSA series on one chart.
- Footer: `Source: <publisher> · <series id> · retrieved <date>`; series
  relayed by World Bank Data360 credit the IMF WEO, GEP or WDI database.
- One y-axis. No dual axes: index both series to a common base or use two
  charts. Do not put a level and its growth rate on one axis.
- Noisy monthly flows that are not seasonally adjusted (monthly receipts,
  outlays, deficits) keep their stored values as a thin line under a derived
  twelve-month average, labelled as derived.
- Cross-economy: identical units, frequency and adjustment → one overlay (at
  most six lines, direct end labels, legend) that replaces the members' single
  charts; otherwise separate charts.
- Forecast thresholds: draw a binary's threshold as a labelled dashed
  horizontal line, the resolution date as a vertical line, scenario ranges as
  light bands, and put the probability next to the threshold. The report
  visualizer adds these overlays for binaries with a `data_anchor`.

## 3. Run the renderer

The research pipeline invokes the bundled renderer after dataset persistence and
citation finalization, using the configured chart interpreter and timeout. Agents
should use the data tools and provide evidence notes; they do not need a shell.
For an operator testing an isolated run directory, the renderer entrypoint is
`scripts/render_data.py --dir <run-directory> --lang en` within this skill. Use
only a known skill path and an explicitly selected artifact directory.

- Input: `$RUN_DIR/data/datasets.json` plus each row's series file.
- `--max N` (default `DATA_SOURCES_CHARTS_MAX`, else 8) caps data charts in
  total. A comparison counts as one chart, ranks by its best member and
  replaces the members' single charts. Selection keeps KIQ-linked series
  first, then cited ones (`source_id`), then catalog order; the rest are
  listed under `dropped`. Zero disables these research charts, preserves
  other chart families, and retires stale data-chart rows even when
  matplotlib is unavailable.
- `--lang zh` uses `title_zh`, Chinese chart text and translated units.
- Outputs: `charts/data_<slug>.png` (+ `.html` interactive twin when plotly
  is installed) and up to two `charts/data_compare_<slug>.png` overlays. The
  twins share one `charts/plotly.min.js` (the app inlines it when serving a
  chart); they embed plotly only when that file cannot be written.
- `charts.json` rows: `{id, title, caption, source_data:
  "data/datasets.json", data_class: "official_statistics", path, html_path?,
  series: [...]}`. Only ids starting with `data_` are replaced; other
  producers' rows stay in place. Reruns replace only the renderer-owned rows. The bridge attaches citations from the current dataset manifest before embedding.
- Manifest captions are digit-free and read the data: the latest value
  against a year earlier and its place in the charted range, or which economy
  is highest and lowest.
- stdout: one JSON line `{charts, skipped: [{series, reason}], dropped}`.
- Exit codes: `0` = at least one chart, `2` = no eligible data, `3` = no
  matplotlib. On `2` or `3`, use a compact table (series | latest | period |
  units | source `[S#]`) and do not narrate renderer internals in the report.
  `REPORT_DATA_CHARTS=false` separately disables the forecast report's official
  chart family while retaining its stored-data context and other figures.

## 4. Embed at the point of use

```markdown
![Unemployment Rate](charts/data_fred_unrate.png)

*Unemployment has risen for six straight months to its highest level since
early in the cycle [S12]; dashed segment = IMF projection.*
```

- Place each figure beside the claim it supports, at most two per section.
- Alt text = the manifest `title`. Keep years and values out of alt text and prose captions; retain the
  exact file paths supplied by the manifest: report audits treat bare numbers there as uncited claims.
- The caption states the takeaway, the time boundary in words, and the
  `[S#]` of every series it relies on; any number in it must match the stored
  data page exactly.
- Name units or seasonal adjustment in the caption when a reader could
  misread them; link the `.html` twin only when interactivity helps.

## 5. Do not

- Chart an internal proxy (source counts, keyword frequency) as if it were data.
- Use rainbow palettes, 3-D effects, or a colour per point.
- Rebase, deflate or annualise a series by hand: request the transform from
  the data tools (`transform="yoy"`) so the stored page matches the chart.
- Present an old or unknown vintage as the latest release. Retrieval time
  alone does not establish publication time or historical availability.
