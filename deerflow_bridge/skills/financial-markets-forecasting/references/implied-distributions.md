# Implied distributions: market prices to probabilities

Load this to turn futures, forwards, OIS, breakevens, options, CDS or prediction-market prices into a labelled **market-implied** row of the distribution table. Every market-implied finding records: instrument, contract month or expiry, price, timestamp and time zone, page fetched. A price without its timestamp cannot be reconciled with anything.

Market prices give **risk-neutral** odds: they embed risk premia, carry and positioning. They are a calibration anchor, not the answer. Name the premium you remove when you convert them.

## 1. What each instrument says

| Instrument | Gives | Read as | Main bias to correct |
|---|---|---|---|
| Commodity futures | Risk-neutral mean of the delivery-month settlement | Centre of the distribution for that month | Unstable premium; as point forecasts, futures rarely beat no-change (prior to verify: central-bank and IMF staff evaluations) |
| Equity index futures | Spot plus carry (rate minus dividend yield) | No directional information | None: use options for shape |
| FX forwards | Interest-rate differential (covered parity) | Carry, not a forecast | Forward premium puzzle: spot often predicts as well (prior to verify: Meese-Rogoff literature) |
| Fed funds and SOFR futures, OIS | Expected average overnight rate over the period | Policy-path odds | Term premium beyond about a year; EFFR-to-target basis; month-end effects |
| Treasury curve forwards | Expected short rates plus term premium | Not expectations alone | Term premium (NY Fed ACM, Fed Board Kim-Wright model estimates, REPORTED) |
| Breakevens and inflation swaps | Inflation compensation | Expected CPI plus risk premium minus TIPS liquidity premium | Both premia move in stress |
| Options | Full risk-neutral distribution | Width and skew | Variance risk premium; skew |
| CDS and bond spreads | Risk-neutral default intensity | Upper bound on real-world default odds | Credit risk and liquidity premia |
| Prediction markets | Event probability | A second opinion | Favourite-longshot, long-dated compression, resolution mismatch |

## 2. Futures and forwards

**Commodity curve (theory of storage).** F(T) = S x exp((r + u - y) x T), with u the storage cost and y the convenience yield.
- **Backwardation** (deferred below front) means the convenience yield exceeds carry: prompt barrels or tonnes are scarce.
- **Contango wide enough to pay storage** ("full carry") means surplus and inventory builds; extreme contango brings floating storage.
- Tightness gauges: front-to-second and front-to-12th-month spreads (Brent, WTI); the LME cash-to-3-month spread; SHFE, INE, DCE and GFEX nearby spreads; regional differentials (WTI-Brent, Brent-Dubai).
- **Consistency check.** Curve tightness should agree with inventories versus their 5-year range (EIA weekly, IEA OMR OECD stocks, exchange warehouse stocks). Backwardation with rising stocks points to a local squeeze, such as Cushing or one exchange's warrants, not global tightness. Exchange warehouse stocks are a small part of total stocks.
- **Which contract settles.** For a price on a date, use the contract trading on that date (front month after its roll) and record its delivery month. Continuous front-month series jump at rolls; ICE Brent and NYMEX WTI expire on different calendars, so check each exchange's expiry rules.

**Policy rates.**
- **30-day fed funds futures (CME).** Price = 100 - the average effective rate over the contract month.
  - For an FOMC decision effective after day d of an N-day month: A = (d x r0 + (N - d) x r1) / N, so r1 = (N x A - d x r0) / (N - d). The probability of a 25 bp cut is (r0 - r1) / 0.25.
  - When few days remain after the meeting, read the next month's contract instead.
  - Remove the current EFFR-to-target-midpoint spread before reading odds on the target range.
- **SOFR futures (3-month, CME)** give 100 - compounded SOFR over the reference quarter; mind the SOFR-EFFR basis.
- **OIS.** The fixed rate equals the expected average overnight rate. A forward OIS between two meeting dates gives that window's expected rate (euro area: ESTR OIS; Japan: TONA OIS).
- **China.** ChinaBond (CCDC) curves are the S1 settlement for CGB yields. FR007 and SHIBOR swap curves (CFETS) price the repo-rate path. CFFEX treasury futures (TS, TF, T, TL) imply forward yields only approximately (cheapest-to-deliver, conversion factors).
- **Path questions** ("below X by December 2027") are deadlines. On a monotone easing or tightening path the end-of-period level decides them; if reversals are plausible, treat them as touch questions. Use the contract covering the settlement period. Settle on the right series: bis:WS_CBPOL/M.US (native monthly, end of period) records the target-range midpoint, upper bound − 0.125, and settles automatically: "upper bound at most X at end-2027" is its 2027-12 value at most X − 0.125. fred:DFEDTARU (the upper bound; end-of-month values of a daily series) anchors the same month but settles manually. Both differ from the effective rate (fred:DFF monthly mean, fred:FEDFUNDS monthly average). FOMC dots (SEP) are the committee's own REPORTED projections, not market prices. Record the market-minus-dots gap with both dates.

**FX forwards.**
- For S quoted as quote-currency units per base unit (USD/CNY = CNY per USD): F = S x (1 + i_quote x T) / (1 + i_base x T). With CNY rates below USD rates, the USD/CNY forward sits below spot by construction: that is not a forecast of appreciation.
- Centre FX on spot unless a regime binds:
  - **Onshore CNY** spot trades within a band around the CFETS central parity (plus or minus 2% since 2014; verify the current band and the fixing mechanism). Watch the CNH-CNY spread and the fixing-versus-model gap as stress gauges.
  - **HKD** sits inside the Linked Exchange Rate System's convertibility zone of 7.75 to 7.85 (verify on the HKMA site). The distribution is truncated, and the real question becomes a regime-break hazard.
  - **Intervention zones** (Japan MOF, PBoC) cap the tails while they last. Their history is published: MOF intervention records, SAFE and PBoC reserves.

## 3. Options to probabilities

**Lognormal shortcut** (prices, FX, indices). Inputs: forward F, strike K, annualized implied vol s for the expiry nearest the horizon, T in years.
- d2 = (ln(F/K) - s^2 x T/2) / (s x root T); then P_RN(S_T above K) = N(d2).
- Median = F x exp(-s^2 x T/2). P10/P90 = F x exp(-s^2 x T/2 -/+ 1.2816 x s x root T).
- Normal-table anchors: N(-1.28) = 0.10, N(-0.84) = 0.20, N(-0.52) = 0.30, N(0) = 0.50.
- Hypothetical illustration: F = 80, K = 100, s = 35%, T = 1. ln(0.8) = -0.223 and s^2 T/2 = 0.061, so d2 = (-0.223 - 0.061)/0.35 = -0.81 and P(above 100) is about 0.21.

**Normal (Bachelier) shortcut** (yields, spreads, policy rates, quoted in bp). P(y_T above K) = N((F - K) / (s_bp x root T)), where s_bp is the normal vol in bp per year. MOVE is a normal-vol index of 1-month Treasury options (check its definition on the publisher's page).

**Use the right vol.**
- **Term.** VIX is 30-day S&P 500 implied vol. Implied vol mean-reverts, so never scale a stressed 30-day reading flat to a year. Use a published longer-dated implied vol, or blend toward the long-run average from stored fred:VIXCLS history; the stored history holds monthly means, so state that.
- **Strike (skew).** Equity index puts carry higher implied vol than calls, persistently since the 1987 crash (widely documented). The ATM lognormal shortcut therefore understates the risk-neutral chance of a large fall: use the vol at the strike or the 25-delta put vol. Oil can show call skew in supply scares, gold often shows call skew, and FX risk reversals give the skew's direction.
- **By hand from a chain page.** P_RN(S_T above K) is about [C(K - h) - C(K + h)] / (2h x DF). A tight call spread is a digital option.
- **Event-day move.** The ATM straddle price is about the expected absolute move to expiry (both are about 0.8 x s x root T x S). For an FOMC, CPI, earnings or OPEC+ date, take expiries just before and just after it: event variance = s_after^2 x T_after - s_before^2 x T_before, and its square root is the priced event move as a fraction of S.

**Public vol sources** (S1 or S2, record timestamp): Cboe VIX, VXN, OVX (crude oil ETF options) and GVZ (gold ETF options); ICE BofA MOVE; CME CVOL indices (SOFR, Treasuries, crude, gold, FX); VIX futures for forward vol. China: CFFEX CSI 300 index options and SSE/SZSE ETF options, where a source publishes their implied vol.

**Touch (barrier) questions.** For a driftless continuous path, P(path reaches K by T) = 2 x P(S_T beyond K) (reflection principle). Daily closes touch less often than intraday prices, and drift toward K raises the odds. Take P_terminal as the floor and 2 x P_terminal as the ceiling. FX one-touch option prices, where quoted, give the touch odds directly.

## 4. Risk-neutral versus real-world (the caveat)

- **Variance risk premium.** Equity index implied vol on average exceeds the volatility later realized (widely documented in the academic literature). Read as real-world odds, risk-neutral spreads, and the left tail especially, are too wide. For an equity downside threshold, shade P_RN toward the empirical h-step rate and record both. Do not shade when realized vol is running above implied (crisis regime).
- **Drift.** Risk-neutral drift is the rate minus the dividend yield. The real-world equity median sits above F by roughly the equity risk premium times T: state the premium you assume and label it judgmental.
- **Commodities and FX.** Premia are small and unstable in sign, so use risk-neutral odds nearly as they are. If a jump event falls before expiry and the event-date vol kink is absent, widen the tails and say why.
- **Rates.** Beyond about a year, forwards include term premium. Subtract a model estimate (ACM, Kim-Wright, REPORTED) for an expectations path and name the model.
- **Credit.** Hazard = spread / (1 - R) and P_RN(default by T) = 1 - exp(-hazard x T), with R the contract's recovery convention (often 40% for senior debt; verify). Spreads exceed expected losses (credit-spread puzzle, widely documented), so the real-world prior is the rating agencies' cumulative default rates by rating and horizon (S&P Global and Moody's annual default studies).
- **Default definitions differ.** Rating agencies count a missed payment after its grace period, a distressed exchange or a bankruptcy. A CDS credit event is a Determinations Committee ruling. The onshore Chinese market may not treat an extension (展期) as a default. Pin the definition in the settlement contract.

## 5. Prediction markets

- **Bracket ladders** (venues such as Kalshi and Polymarket have listed ranges for index closes, oil and gasoline, Treasury yields, CPI prints and Fed decisions; check what is live).
  - CDF at bracket edge b = the sum of bracket prices up to b, divided by the ladder sum (removes overround).
  - On "above K" ladders, odds must fall as K rises. Violations mean stale quotes: use bid-ask mids and ignore last trades in thin books.
- **Resolution.** Each market names its source and time, such as an index close from a stated data provider. Compare it with the question's settlement contract: intraday versus close, a day versus a monthly average, a different index or contract month. A mismatched market is a reference, not an equivalent.
- **Biases.**
  - Favourite-longshot: cheap tails are overpriced, most of all in thin markets, so shade small probabilities down.
  - Long-dated markets: capital lock-up and fees pull prices toward 0.5, so near-certain outcomes trade below 1. Discount extremes beyond about six months.
  - When a deep options market prices the same threshold, prefer it and use the prediction-market gap as a check.
- Query craft, liquidity filters and the Prediction Market Signals table are in the prediction-markets skill.

## 6. Reconciling into the distribution table

1. **Market-implied row.**
   - P50: the lognormal median F x exp(-s^2 x T/2) of the forward or futures (commodities), the futures or OIS rate (rates), or spot for FX and equities, plus any stated drift.
   - P10/P90: from skew-aware implied vol.
   - Label: instrument and timestamp.
2. **Empirical row.** The forecast stage's h-step quantiles: series, window, h, n (see empirical-and-volatility-base-rates.md).
3. **When the widths disagree by more than about a third**, find the regime first: current implied versus long-run vol, a peg or band, yield-curve control, a pending event. Never average a risk-neutral and an empirical quantile without naming the premium removed.
4. **Judgmental shifts** need a named driver with dated evidence. Size them in vol units (for example +0.3 sigma for a dated supply decision) so reviewers can audit them. In the report they explain where the evidence leans against the plan's frame; they do not create a new distribution or probability list.
5. **Map to scenarios.** Each canonical scenario is a range of the settlement statistic. Give the market-implied mass of each range beside the plan weight. A gap of more than about 10 points needs a stated reason in the scenario analysis, not a restated probability list.
