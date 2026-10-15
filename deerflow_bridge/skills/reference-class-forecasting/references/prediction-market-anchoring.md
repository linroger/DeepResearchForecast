# Prediction-market anchoring

This file covers how to use a market price as an anchor. Query craft, the market tool, relevance filtering and the "Prediction Market Signals" table live in the prediction-markets skill. The thresholds below are house rules of thumb for this pipeline, not measured facts.

## 1. Where markets enter this pipeline

- **v3.** KIQ agents have no market tool. After the report is written, the engine collects markets: prediction_markets.json plus an appended "Prediction Market Signals" section. The forecast stage then cites each overlapping market (market_anchor) and must explain any divergence over 10 points. Research therefore owes two things:
  - resolution terms exact enough that a market can be matched to them;
  - base rates the market can be compared with.
- **Legacy.** prediction_market_search runs once, in the opening pass, with one refresh at final synthesis. If it returns nothing relevant, record no_market_coverage and stop.
- **Forecasting platforms are not markets.** Metaculus, Good Judgment Open and INFER aggregate forecasters without money at stake. Treat a community forecast as S2 evidence carrying its own resolution text, and run the same match checks (§2) on it.
- **Market odds quoted in news** (a page saying "markets give 70%") are REPORTED second-hand. Record the venue, date and contract if the page names them; otherwise treat the figure as colour.

## 2. Is this market an anchor? Ordered checks

1. **Resolution match.** Compare against your question: the event, the threshold and unit, the deadline and its time zone, the settling source, and the edge rules (early resolution, ties, cancellation, "announced" vs "in effect"). Any difference makes it a near-miss: map it (§4) before comparing.
2. **Liquidity tier** (house rule):

| Tier | Volume / liquidity | Use |
|---|---|---|
| Strong | volume of USD 1M or more, liquidity of USD 100k or more, traded within a day | anchor |
| Usable | volume of USD 100k or more | check, after bias correction |
| Weak | below that | colour only: one trader can set the price |

   The market tool's own volume floor screens for relevance, not for trust.
3. **Time to resolution.**
   - Up to 6 months: a strong, matched market is the best single anchor.
   - 6 to 24 months: apply the bias corrections in §3.
   - Beyond 2 years: weak whatever the volume.
4. **Internal consistency.** Sibling contracts (a ladder, other deadlines, another venue) should agree within a few points. When they do not, the quotes are noisy or stale.
5. **Freshness.** A last trade before the latest catalyst means re-fetch (legacy) or downgrade the market.

## 3. Biases and how to correct them

- **Favourite–longshot bias.** In betting and prediction markets, low-probability contracts tend to trade above their realized frequency and favourites below it. Academic calibration studies document this, including evidence that the bias grows with time to expiry (Page and Clemen). Verify against venue calibration data where it is published.
  - Correction: shade prices below about 15 down, and prices above about 85 up, by a few points. Never shade a price to 0 or 100.
- **Capital cost in long-dated contracts.** Unless the venue pays interest on positions, a long-dated position forgoes the risk-free return, which pulls long-dated prices toward the middle.
  - Example: at 4% a year over 2 years, the forgone return is about 8%. Buying "No" at 0.95 earns 5.3%, less than that, so "Yes" can sit near 0.05 even when the true chance is about 1%. A near-certain "Yes" can trade near 0.92.
  - Read a long-dated longshot price as an upper bound, and a long-dated favourite price as a lower bound.
- **Ladders and overround.**
  - Yes prices across mutually exclusive outcomes can sum above 1. Divide each by the sum before reading it as a probability: with a sum of 1.08, 0.27 becomes 25%.
  - Bucket ladders give a distribution: P(X ≥ a) is the sum of the buckets at or above a.
- **Term structure.** For the same event, P(by T) must not fall as T moves later, and P(by T2) − P(by T1) is the mass between the two deadlines. A violation means stale or thin quotes, so use neither leg.
- **Trader-base skew.** Partisan or community enthusiasm can tilt political and crypto-adjacent markets. Before treating a gap as information, compare with another venue, a poll-based model or the base rate.
- **Thin-market moves.** One large order can move a thin market, and the price then drifts back. For weak-tier markets, read the level over several days, not the last trade.
- **Oracle and rules risk.** Disputes and clarifications (an oracle vote, a venue ruling) can settle on a reading different from yours. Read the rules text and any clarification posts, and record the rule that matters.

## 4. Mapping a near-miss market

**Common mismatches:**
- announcement vs effective date;
- "by" vs "in";
- ever-touch vs end-state;
- a different threshold, or inclusive vs exclusive bounds;
- a different settling source (first print vs revised; a media call vs certification);
- "ceasefire announced" vs "ceasefire holding";
- the deadline's time zone.

**Map, do not copy:**
- **Threshold differs:** interpolate between neighbouring contracts on the ladder.
- **Deadline differs:** convert through the implied hazard, assuming it is constant, and say so. From P' by T' years, p = 1 − (1 − P')^(1/T'), and then P(by T) = 1 − (1 − p)^T. Example: 40% by 2 years → p = 22.5% a year → 1 year ≈ 22.5% and 3 years ≈ 53.5%.
- **Ever-touch market, end-state question:** end-state ≈ touch ÷ 2 for a driftless series. Treat it as a rough upper guide, not an identity.
- **Announcement market, effective-date question:** multiply by P(effective | announced) from the policy class in the base-rate recipes.
- **Record the chain** in the market-comparison row: market price → mapped value → our anchor → the gap and its reason.

## 5. The divergence rule

- When our probability and the mapped, bias-corrected market differ by more than 10 points, name which reason applies:
  - (a) a resolution mismatch that was not fully mapped;
  - (b) a bias correction (longshot, long-dated);
  - (c) a thin or stale market;
  - (d) evidence the market lacks. This needs S1 evidence and a mechanism, and it is the rarest valid reason.
- "The market is wrong" without one of these is not a reason. Neither is converging by copying: when the two agree, still show the base rate and the market side by side.
- **Which to start from:**
  - If the market is strong-tier, matched and resolves within 6 months, start from the market and adjust only for named evidence.
  - If it is weak or long-dated, start from the base rate and use the market as a check.
  - To blend the two, average in log-odds (probability toolkit §9).
- **Scenario weights are fixed at plan time and are never re-weighted to a market.** A large gap between the market and a scenario-derived binary goes into the bridge's "reads vs frame weight" column, and into a signpost for what would close the gap.

## 6. What to record for each market used

| Field | Content |
|---|---|
| Identity | venue, market ID, question text |
| Resolution | resolution source and the deciding rule (quoted briefly) |
| Price | P(yes), and whether it is the last trade or the midpoint |
| Depth | volume, liquidity, tier |
| Timing | end date, fetch timestamp |
| Mapping | siblings consulted, mapping applied, mapped value |
| Adjustment | bias note, divergence reason |
