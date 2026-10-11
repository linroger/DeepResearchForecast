# Chart patterns for official statistics

Reference for `data-visuals`. Read the section you need; the renderer already
implements the default single-series and cross-economy patterns.

## 1. Selection matrix

Pick the measure the forecast is about, then the form. When two rows seem to
fit, prefer the simpler form.

| Reader question | Measure | Form | Notes |
|---|---|---|---|
| Where is the level going? (CPI index, GDP, debt, oil price) | Level in published units | Line, native date axis | Non-zero baseline is fine for a line; say "index" or the currency year in the axis label. |
| Is it accelerating or cooling? (inflation, output growth) | Growth rate (`transform="yoy"`, or the published percent-change series) | Line with a zero line | Never plot the level and its growth rate on one axis; use two charts. |
| How large is it relative to the economy? (deficit, debt, credit) | Share (% of GDP) as published | Line; bar only for a single cross-section year | Do not divide two series yourself unless both are stored and the method is stated. |
| How do economies compare now? | One period, same units and definition | Sorted horizontal bar or dot plot | Name the period in the caption; mixed latest periods need a footnote. |
| How do economies compare over time? | Same flow/indicator, same units and frequency | Overlay (≤ 6 lines, direct end labels) or small multiples | Different units → separate charts; never two y-axes. |
| Is it unusually high or low? | Level plus its own history | Line with the historical range or a long-run average as a reference line | The reference must come from the stored data; state the window. |
| What does the official outlook say? | Explicitly classified publisher projections | Line with dashed projection segment | Respect canonical status before any `projection_from` fallback; label publisher and known vintage. Unknown WEO/GEP status stays unknown. |
| How did the outlook change? | Same target year across vintages | Revision line or dumbbell | Needs at least three vintages from the same publisher; otherwise a table. |

Frequency rules: plot at the native frequency (monthly as monthly). If daily
data were aggregated to monthly averages, say so in the subtitle or caption.
Do not mix frequencies on one axis. Keep SA and NSA series apart.

## 2. Forecast overlays

Use these when a chart supports a forecast question. Each overlay must trace
back to a stored series, a stated binary threshold, or a published projection.

- **Threshold line.** A binary such as "Will CPI inflation exceed the stated
  threshold in the resolution month?" gets a dashed horizontal line at the
  threshold, labelled with the comparator ("> threshold") and the model
  probability. Use one neutral ink colour; the series keeps its colour.
- **Horizon line.** A thin vertical line at the resolution or forecast
  horizon date, labelled "Forecast horizon". Extend the x-axis to it even when
  no data exist yet, so the reader sees the remaining distance.
- **Scenario bands.** When scenarios carry explicit numeric ranges for the
  same series and units, draw each as a light horizontal band between the
  horizon line and the axis edge, labelled with the scenario name and its
  probability. Never invent a range around a point estimate.
- **Projection band.** Explicit publisher projections stay dashed. Use a
  `projection_from` band only when compatible with the canonical point statuses.
  Unknown, preliminary and estimated points keep their separate labels/markers.
  The model's own forecast, when shown,
  uses a different mark (for example a diamond at the horizon) and is labelled
  as the model forecast, never as the publisher's projection.
- **Fan chart.** Only when quantiles are actually available (for example an
  ensemble's 10th/50th/90th percentiles for the same series). Shade nested
  bands from light (wide) to darker (narrow) in one hue, keep the median as a
  line, and state the quantiles in the legend.
- **Event markers.** A dated policy decision or data release can be a small
  labelled tick on the x-axis when it explains a turn in the line. Limit to
  three; more belongs in the timeline chart.

Keep the text of overlays short and free of bare years in alt text and
captions; dates live on the axis.

## 3. Captions that pass the report audits

- Lead with the takeaway, then the time boundary in words ("over the past
  decade", "since the pandemic trough"), then `[S#]` for each series used.
- Every number in a caption must appear on the stored data page for the
  cited `[S#]`; prefer words for direction and size ("roughly doubled").
- Alt text and file names stay digit-free (`charts/data_fred_unrate.png`,
  not `cpi-2026.png`).
- Say "projection" for publisher outlooks and "forecast" for the report's
  own estimates.

## 4. Visual QA checklist

Run this before embedding any figure:

1. The chart answers the one question written for it; otherwise drop it.
2. Every mark comes from a stored observation or a published projection.
3. Units, index base, currency year and seasonal adjustment are on the chart.
4. Projection segments are explicitly supported by status/metadata; unknown or preliminary values were not reclassified by a cutoff.
5. Gaps are visible as breaks, not bridged.
6. Only the latest confirmed historical observation is marked; its period matches the data page. Fiscal labels and partial coverage come from keyed period metadata.
7. One y-axis; overlaid series share units, frequency and definition.
8. At most six lines; each line has a legend entry and a direct label.
9. No label overlaps a line end, another label, the legend or the footer.
10. Tick labels are round numbers; large values use K/M/B/T suffixes.
11. The footer names provider, series id and retrieval date.
12. Alt text and caption are digit-free except cited values with `[S#]`.
13. The PNG exists at the manifest `path`; the `.html` twin, when linked,
    exists at `html_path`.
14. Rerunning the renderer reproduces the same files.
