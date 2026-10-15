---
name: financial-markets-forecasting
description: Forecasts of market-determined numbers and listing or default events at or by a date - asset and stock prices, index levels, Treasury and sovereign yields, credit spreads, FX rates, oil, gas, gold, copper and lithium prices, market caps and valuations, IPO timing, proceeds and rankings, bond or issuer defaults. Triggers include "10-year yield above", "oil price by end of 2026", "S&P 500 level", "USD/CNY", "market cap", "largest IPO", "credit spread", "default by"; 股价, 市值, 估值, 指数点位, 国债收益率, 利差, 汇率, 人民币汇率, 油价, 金价, 铜价, 碳酸锂价格, 大宗商品价格, IPO, 上市, 募资规模, A股, 港股, 科创板, 违约. Adds settlement-source mapping, market-implied distributions (futures, OIS, options, prediction markets), volatility-scaled base rates from long official history, catalyst calendars and staged listing pipelines. Not for policy-rate decisions, inflation or growth outcomes (use macro-research), industry market size (use industry-forecasting) or leadership on non-price metrics (use competitive-landscape-forecasting).
---

# Financial Markets Forecasting

Forecast market-determined numbers, listings and defaults at or by a date: pin the settlement contract, read the market-implied distribution, scale it against long official history, and leave anchors, catalysts and signposts the forecast stage can settle.

## Activation

Lead when the outcome is a price, yield, spread, FX rate, commodity price, index level, market cap, IPO timing, size or rank, or a default, at or by a date. Pair with:
- **macro-research** for policy-rate or inflation outcomes (this skill only translates futures, OIS and breakevens into odds);
- **competitive-landscape-forecasting** for "largest IPO" or "most valuable company" rankings (this skill supplies listing stages, size conventions and relative-volatility odds);
- **industry-forecasting** when a commodity price sits inside a sector outlook.

Adds to the research core: settlement-contract mapping, the pipeline's anchor rules for daily market series, market-implied versus empirical distributions beside cited views, catalyst calendars and staged listing pipelines.

## Plan

- **KIQ (general): settlement contract**: instrument, publisher, fixing time/zone, statistic (level on date | touch by date | average | rank), price or total return, currency.
- **KIQ (data) worded as a base rate** ("historical 12-month changes in ..."), with data_needs so long history is stored (start 30 years back; monthly keeps 20): fred:DGS10, fred:DEXCHUS, fred:DCOILBRENTEU, imf:PCPS/G001.PGOLD.USD.M (fred:SP500: 10 years, ICE spreads: 3). A/H-share indices, stocks, IPOs: exchange S1, no proxy.
- **KIQ (general): market-implied distribution** at the horizon: futures/forward, OIS, implied vol and skew, liquid prediction markets.
- **KIQ (general): fundamental anchor**: commodity balance, inventories, spare capacity; rates = expected path + term premium; FX rate gaps, official tolerance; equities = earnings x multiple (reverse DCF); IPO pipeline by stage.
- **KIQ (general): dated catalyst calendar** to the horizon.
- **Actor KIQs** (price-setters): central bank, finance ministry, OPEC+, PBoC fixing, CSRC/exchanges (IPO pace), issuers.
- **Scenarios are price regimes**: MECE ranges of the settlement statistic cut at the question's thresholds, each naming its driver. Rank asks (largest, top 5): the competitive-landscape leader frame leads; ranges go into theses.
- **Weight base-rate-first.** Centre on the forward (FX, equities: spot) or a liquid market probability, else no change; give each range its mass under sigma x root(years) (±1 sigma bins: ~16/68/16). Without scout vol, long-run annualized priors (verify on history): equity indices 15-25%, oil 30-40%, gold 15%, copper 20-25%, major FX 7-11%, USD/CNY 2-5%, 10-year yield ~1 pp. Tilt at most ~10 points per regime for evidenced skew or a dated catalyst; no tail regime exceeds its historical frequency without one.

## Investigate

**Quick path:**
1. Pin the settlement source (exchange settlement notice, index provider, Fed H.15/H.10, Treasury, ECB, CFETS, ChinaBond, SSE/SZSE/BSE, HKEXnews, SEC EDGAR): publisher, fixing time and zone, statistic, price or total return, roll rule.
2. data_get the catalog series with start 30 years back **on its first call**; the forecast stage's h-step base rate uses that window. Record latest value, date, window start (fred:SP500, ICE spreads: short).
3. A dated market-implied anchor for the horizon month: futures/forward (CME, ICE, LME, SHFE/INE, DCE, GFEX, CFFEX) or OIS, plus ATM implied vol (VIX, MOVE, OVX, CVOL). P(below K) = N(ln(K/F)/(σ√T) + σ√T/2), yields N((K-F)/(σ√T)); REPORTED.
4. Catalysts from publishers' calendars: central-bank meetings, data releases, auctions, OPEC+, earnings, index reviews, lock-ups.

**Chinese questions:** search Chinese and English (人民币中间价, 中债收益率, 上市委会议).

**Standard:** skew; curve shape and time spreads vs inventories' 5-year range; spare capacity; reverse DCF; EIA/IEA/OPEC balances side by side. **Deep:** implied vs realized vol; prediction-market brackets; listing-cohort completion. **IPOs:** stage each candidate from dated S1 status pages.

**Record each finding:** statistic, value, unit, as-of date and zone, source; then `anchor:` series ID, period (YYYY-MM), units, comparator, threshold, or `not anchorable:` reason; label market-implied, empirical or cited view. Actors: instrument, decision calendar, stated reaction function, dated precedents, constraints.

**Anchor rule:** daily price, yield, spread and FX series are stored as monthly means and settle by hand: they anchor only monthly averages, never a single-day close or a touch; native monthly IMF commodity and BIS FX series settle automatically.

**Traps:**
- Spot read as forecast → the curve sets the risk-neutral centre; FX forward points are carry, not a view.
- Risk-neutral read as real-world → implied above realized vol and put skew make downside tails rich.
- Touch read as terminal → driftless P(touch) is about 2 x P(ending beyond).
- One CNY rate assumed → CFETS fixing, onshore close, offshore CNH differ.
- Sell-side targets read as distributions → S3, clustered above spot.
- IMF WEO oil path read as independent → it is futures-based.

**Stop:** settlement pinned, long series stored, a dated market-implied anchor and calendar found; else yield stop.

## Synthesize

Required exhibits (markdown tables of cited facts):
1. **Settlement definition:** instrument, publisher, fixing time and zone, statistic, adjustment, anchor (series, period, units) or why none fits.
2. **Distribution at the horizon:** P10/P50/P90 non-exceedance, one row per method in the evidence, labelled market-implied (instrument, date), empirical (series, window, h, n, the regimes the window spans) or a cited forecaster's view (publisher, date); then say which row fits the evidence best and why the rows differ, without a new reconciled row. Never average rows built on different statistics.
3. **Catalyst calendar:** date, event, published implied move, the scenario it discriminates.
4. **Signposts:** indicator, threshold, date, the scenario it confirms or kills.

Conventions: "at end of YEAR" is the last trading day's official close; "by DATE" means any official close unless intraday is stated; an average is the mean of official fixings. Quantiles are non-exceedance; beyond P10/P90 use empirical tails, not the normal (fat tails); never sum marginal P90s. Label risk-neutral probabilities as such. Analyse each canonical scenario as a range of the settlement statistic, say whether market-implied odds agree, and name its falsifier. For rankings, state the proceeds or market-cap convention.

## Gaps

- Is the settlement contract pinned (publisher, fixing time, statistic, price or total return)?
- Is a dated market-implied anchor for the horizon recorded?
- Is the base-rate series stored with long history and its window start stated?
- Is the risk-neutral versus real-world adjustment stated for the tail forecast?
- Is there a dated catalyst calendar through the horizon?
- For commodities, are inventories, spare capacity and curve structure covered?
- For listings, is each candidate staged with a date and the ranking convention fixed?
- Do the price-setting actors have reaction-function evidence?

## References

- [references/implied-distributions.md](references/implied-distributions.md): load to turn futures, forwards, OIS, breakevens, options or prediction-market brackets into probabilities, with their biases.
- [references/empirical-and-volatility-base-rates.md](references/empirical-and-volatility-base-rates.md): load to build or check a base rate from catalog history, scale horizons, or handle touch, average, ranking and default questions.
- [references/listings-and-ipos.md](references/listings-and-ipos.md): load for IPO timing, size or ranking questions on A-share, Hong Kong or US venues.
