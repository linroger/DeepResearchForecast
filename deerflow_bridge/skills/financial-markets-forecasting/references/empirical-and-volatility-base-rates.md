# Empirical and volatility base rates from catalog history

Load this to build, check or correct the **empirical** row of the distribution table. The forecast stage computes most of the numbers itself, from the stored series. The research job is to store the right series with the right window, record what the stage cannot see, and flag where its sample misleads.

## 1. What the forecast stage computes

For each binary with a `data_anchor` on a stored series:
- **h** = the number of periods from the latest complete historical observation to the anchor period.
- **Sample** = every overlapping h-step change in the stored history. Changes are absolute, in the series' own units. A seasonal monthly series without seasonal adjustment uses starts from the same calendar month.
- **p** = the share of (latest value + change) that satisfies the comparator. It needs n of at least 30. The stage also reports quantiles p10 to p90 and `sigma_distance` = (threshold - latest) / sd of the changes. Its outside-view block adds the latest value's percentile in the stored history and, for level series, percent-change quantiles.
- **Excluded:** projections, estimates, preliminary values and the open month.

Storage facts that decide the sample:
- **The first `data_get` of a series fixes its window for the run.** Later requests return the same stored generation with a coverage note. Request `start` 30 years back on the first call, or have the planner name the series in a base-rate KIQ's data_needs so the engine stores the long window.
- **A stored series keeps its newest 240 observations**: 20 years of a monthly series, 60 of a quarterly one.
- **Without `start`,** you get about 10 years: 120 monthly points, about 108 overlapping 12-month changes, but only about 9 independent years.
- **Daily series are stored as calendar-month means** (policy targets and stocks as end-of-month values). The open month is partial and excluded, and the latest daily value is shown separately in the stored page: record it.
- **Settlement.** Daily-derived monthly series are flagged resolution-unsafe: an anchor on them still yields the base rate and watch rows, but it resolves "manual". Native-monthly series can settle automatically once the period has ended and been fetched: imf:PCPS/G001.POILBRE.USD.M, imf:PCPS/G001.PGOLD.USD.M, fred:PCOPPUSDM, bis:WS_XRU/M.CN.CNY.A, fred:FEDFUNDS, bis:WS_CBPOL/M.US. When the question allows a monthly average, prefer them; IMF calls are slow, so fetch once.

## 2. Correcting the stage's sample

- **Absolute changes on price levels.** A USD-per-barrel or index-point change drawn from a low-price era understates today's dispersion, and one from a high-price era overstates it. For prices, FX and indices, judge thresholds on the percent-change quantiles: required move = K / S - 1. Yields and spreads (percent units) use absolute changes correctly. But the near-zero-rate eras (US 2009-2015 and 2020-2022; long stretches in Japan and the euro area) compress the sample, so condition on the rate regime.
- **Stale start.** The stage starts from the last complete monthly mean, up to about six weeks old. If the latest daily value has moved materially, re-centre: shift the stage's quantiles by (latest daily - latest monthly mean), and say so.
- **Overlap.** L observations give only about L / h independent h-step outcomes: 240 months at h = 36 is fewer than 7. Long-horizon empirical quantiles then describe a handful of episodes. Name them (the largest rise and fall readable from the stored page, with dates) and widen rather than trust the tails.
- **Monthly mean versus a single day.** For a random walk with monthly variance sigma^2:
  - mean-to-mean change over h months: variance sigma^2 x (h - 1/3);
  - point-to-point: sigma^2 x h;
  - a month-end close versus that month's mean: about sigma^2 / 3 extra (sigma^2 / 6 for a random day in the month).
  The difference is small at h of 6 or more. The larger error is answering a single-day question with a monthly average at all.
- **Touch questions.** The stage's p is a terminal or period-value probability. For a driftless path, P(touch by T) is between P_terminal and 2 x P_terminal (reflection principle), nearer the upper end for intraday touches.
- **Period-average questions.** For an average over a window starting T0 from now and lasting L (same time unit), variance = sigma^2 x (T0 + L / 3). Example: averaging over a calendar year that starts 2.5 months from now gives sigma^2 x (2.5 + 4) = 6.5 sigma^2 month-units. The point value at that year's end gives 14.5 sigma^2. The average's sd is about two thirds of the year-end sd.

## 3. Volatility scaling by hand

- **Square-root rule (iid).** sigma_h = sigma_annual x root(h in years). Monthly = annual / root 12, weekly = annual / root 52, daily = annual / root 252.
- **Quantiles (log scale, normal approximation).** P10/P90 = median -/+ 1.2816 sigma_h, and P25/P75 = median -/+ 0.674 sigma_h. At monthly and longer horizons this is adequate for P10/P90. Beyond P5/P95 use empirical quantiles: fat tails matter there.
- **Backing sigma out of empirical quantiles.** sigma_h is about (p90 - p10) / 2.56. Compare it with implied vol x root T. The ratio is the regime signal for the reconciliation.
- **Which sigma.**
  - Under a year: the current regime (implied vol, or recent realized vol), because volatility clusters and shocks decay over months (GARCH persistence, widely documented).
  - Multi-year: blend toward the long-run sigma from the stored history.
- **Mean reversion versus random walk.** Yields, credit spreads, vol indices and real commodity prices tend to mean-revert over multi-year horizons, so dispersion grows more slowly than root h. Major FX rates and equity indices are close to random walks at 1 to 5 years, equities with positive drift.
  - **Variance-ratio check:** if the stage's 12-step p10-p90 width is well below the 1-step width x root 12, mean reversion is in the sample. Use it, except when a regime shift is under way.

## 4. Regimes and fat tails

Before trusting a full-sample rate, ask whether the stored window spans one regime. Each item is a precedent to verify, not a current fact:
- **Policy regimes.**
  - CNY: the July 2005 reform, the 2008-2010 re-peg, the band widenings of 2012 and 2014, and the August 2015 fixing reform. A 20-year USD/CNY sample mixes a crawling peg, a hard peg and a managed float, so it is not one distribution.
  - Japan: yield-curve control from 2016 to 2024 pinned the 10-year JGB.
  - Zero-rate eras: these compressed yield changes.
- **Market-structure regimes.**
  - Oil: US shale's supply response, OPEC+ coordination since late 2016, and the negative WTI price of April 2020, also in the daily fred:DCOILWTICO spot series: monthly means dilute that outlier but do not remove it.
  - Indices: licensed FRED histories are short (catalog notes: fred:SP500 about 10 years, the ICE BofA spreads such as fred:BAMLH0A0HYM2 about 3), so state the stored window start; with h of a year or more a 3-year window gives the stage fewer than 30 samples.
- **Correlation regimes.** The stock-bond correlation has flipped sign between low- and high-inflation eras. A hedge assumed in one regime fails in the other.
- **Fat tails and jumps.** Daily returns are strongly fat-tailed; monthly and annual changes are closer to normal, but jumps remain (devaluations, OPEC price wars, sanctions, circuit breakers). With fewer than about 100 independent windows, never claim a P1 or P99.
- **Known binary events before the horizon** (election, OPEC+ meeting, peg review, debt-ceiling X-date, index decision): use a mixture, P = P(event) x distribution given the event + (1 - P(event)) x distribution without it. Never use one smoothed distribution.

## 5. History the catalog lacks

There are no catalog series for A-share, Hong Kong or other non-US indices, CGB yields, single stocks, LME or SHFE metals beyond the IMF and FRED monthly prices, lithium carbonate futures, or IPO statistics. Use instead:
- **S1 historical pages.** CSI, SSE, SZSE and Hang Seng index providers; ChinaBond yield curves; CFETS fixings; exchange fact books and yearbooks (HKEX, SSE, SZSE); exchange settlement histories (LME, SHFE, GFEX, CME, ICE); the World Bank Pink Sheet (monthly commodity prices from 1960).
- **S2 academic datasets.** For example, the long-run US equity and earnings series published by academic authors.

Values computed from these pages are REPORTED. The stage cannot compute on them, so derive the few statistics by hand: the count of years with a fall larger than X, the largest h-step moves with dates. Record the window and n.

## 6. Recipes by question type

| Question | Base-rate method | Anchorable? |
|---|---|---|
| Close on a date | Stage terminal rate on monthly means, re-centred on the latest daily value; percent-change quantiles for price levels | No (single day): record the settlement source; offer a monthly-average companion if useful |
| Monthly or annual average above K | Stage rate; period-average variance sigma^2 x (T0 + L/3) | Yes: the month, or a native annual series |
| Touch by a date | Between P_terminal and 2 x P_terminal | No |
| A overtakes B (market cap, price ratio) | Use x = ln(A/B). sigma_rel = root(sigma_A^2 + sigma_B^2 - 2 rho sigma_A sigma_B) and P(A above B at T) = N(ln(A0/B0) / (sigma_rel root T)), driftless. Hypothetical: sigma_A = sigma_B = 40%, rho = 0.6 gives sigma_rel = 0.36; A 20% smaller (ln 0.8 = -0.223) at T = 1 gives z = -0.62 and P about 0.27 | No |
| Rank among k names | Pairwise odds as above; keep ranks consistent (competitive-landscape-forecasting) | No |
| Default by a date | Real-world prior: rating agencies' cumulative default rate for the rating and horizon. Market-implied: the CDS hazard (implied-distributions.md). Onshore Chinese ratings are not on the global scale (prior to verify), so map them before using global tables | No |
| IPO timing or size | Stage-conditioned pipeline odds (listings-and-ipos.md) | No |

## 7. How to write a base-rate finding

Write one bullet per series, values exactly as stored:
- `fred:DGS10, 12-month changes: stored window <first month> to <last complete month> (<n> monthly means); latest complete month <value> Percent; latest daily <value> (<date>); largest 12-month rise <+x> pp (to <month>), largest fall <-y> pp (to <month>); regime note: <one clause> [S<n>] (REPORTED)`.

Then the anchor line the forecast stage needs:
- `anchor: imf:PCPS/G001.POILBRE.USD.M, 2027-12, U.S. dollars per barrel, >=, <threshold>`, or `not anchorable: single-day ICE Brent settlement; daily series stored as monthly means`.

Record the h you intend: the horizon month minus the latest complete month. n is about the complete stored observations minus h, and below 30 the stage gives no horizon base rate (its outside-view block falls back to a standard 12-month window). A short licensed history or a default 10-year window can cause this at multi-year horizons: say so.
