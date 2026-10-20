# US economic outlook

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging. Forecasts with a market-implied probability are benchmarked against live prediction markets (markets are calibration anchors, not ground truth).

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme | Market P(yes) (Polymarket) |
|---|---|---|---|---|---|
| F1 | The US enacts a corporate tax increase by 2027-12-31. | 30% | A signed federal statute raises the corporate tax rate by 2027-12-31. | policy | 30% (Δ+0pt) |
| F2 | The US enacts a household tax rebate by 2027-12-31. | 80% | A signed federal statute authorizes a household rebate by 2027-12-31. | policy | 80% (Δ+0pt) |
| F3 | US unemployment rate > 4% in June 2027. | 70% | fred:UNRATE > 4% in 2027-06. Official resolution: fred:UNRATE > 4% for 2027-06. | macro | — |
| F4 | The effective federal funds rate < 3% in December 2027. | 40% | fred:FEDFUNDS < 3% in 2027-12. Official resolution: fred:FEDFUNDS < 3% for 2027-12. | macro | — |
| F5 | US industrial output growth exceeds 2% in 2027. | 15% | The official annual industrial output growth exceeds 2% for 2027 by 2028-12-31. | macro | — |
| F6 | US retail sales growth exceeds 2% in 2027. | 25% | The official annual retail sales growth exceeds 2% for 2027 by 2028-12-31. | macro | — |
| F7 | US housing starts growth exceeds 2% in 2027. | 35% | The official annual housing starts growth exceeds 2% for 2027 by 2028-12-31. | macro | — |
| F8 | US business investment growth exceeds 2% in 2027. | 65% | The official annual business investment growth exceeds 2% for 2027 by 2028-12-31. | macro | — |
| F9 | US real exports growth exceeds 2% in 2027. | 75% | The official annual real exports growth exceeds 2% for 2027 by 2028-12-31. | macro | — |
| F10 | US real imports growth exceeds 2% in 2027. | 85% | The official annual real imports growth exceeds 2% for 2027 by 2028-12-31. | macro | — |

_10 forecasts; 7 high-conviction (≥70% or ≤30%); 9 with objective criteria._

### Market Cross-Check

_Deterministic cross-check of forecast probabilities against live prediction-market implied probabilities. Markets are calibration anchors, not ground truth; divergences over 10 percentage points whose rationale does not cite the market are flagged for explanation._

| # | Forecast | Model P | Market P(yes) | Δ (pp) | >10pp verdict | Market |
|---|---|---|---|---|---|---|
| F1 | The US enacts a corporate tax increase by 2027-12-31. | 30% | 30% | +0pt | within band | [The US enacts a corporate tax increase by 2027-12-31.](https://polymarket.com/event/synthetic-market-a) |
| F2 | The US enacts a household tax rebate by 2027-12-31. | 80% | 80% | +0pt | within band | [The US enacts a household tax rebate by 2027-12-31.](https://polymarket.com/event/synthetic-market-b) |
<!-- binary-forecast-block:end -->

> Policy and household demand could shape the outlook.

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| Unemployment Rate — United States | Percent | 4.2% | 2026-09 | — | 4.2% to 4.2% | — | [S1] |
| Federal Funds Effective Rate — United States | Percent | 3.5% | 2026-09 | — | 3.5% to 3.5% | — | [S2] |

## Demand outlook

Household demand could weaken if financing becomes more costly. A household facing a higher refinancing payment might defer a discretionary purchase while maintaining essential spending. That response would make the composition of demand relevant to the outlook: resilient necessities would not by themselves demonstrate strength in durable purchases. Businesses exposed to discretionary demand could respond by reducing orders, which might then affect hiring decisions.

The expansion scenario would remain plausible if income growth supported spending despite these pressures. The contraction scenario would become more concerning if weakness spread from optional purchases into employment and incomes. A useful interpretation would consider those mechanisms together, while allowing for delays between financing conditions and spending choices. This conditional account does not establish that any of these changes has already occurred. Future official observations would be needed to adjudicate the stated forecast contracts.

## Policy channels

A more restrictive policy stance would constrain investment plans through several possible channels. Firms could demand a higher expected return before committing capital, lenders could reconsider credit terms, and managers could retain cash while uncertainty remained high. Each channel would have a different transmission delay. A financing announcement would therefore provide less information than evidence that firms had actually changed the timing of planned projects.

A tax change could also alter the distribution of incentives across businesses. The forecast of a corporate tax increase concerns an enacted statute and its specified deadline; political discussion alone would not satisfy that contract. A household rebate represents a distinct proposition with different recipients and a separate resolution rule. Either proposal could fail independently. The analysis would therefore preserve both uncertainties instead of inferring one policy outcome from the other or treating either policy as a complete economic scenario. Subsequent policy evidence would need to match each original question.

## Alternative paths

Supply improvements could support a continued expansion even if demand became less vigorous. If firms encountered fewer production constraints, they could deliver existing orders with less disruption. Greater reliability might allow businesses to carry smaller precautionary inventories and redirect resources toward productive investment. These possibilities describe a conditional path and should not be interpreted as observations of current business conditions.

The alternative contraction path would involve a broader deterioration that supply improvements could not offset. Its plausibility would depend on the interaction between employment, household incomes and investment plans. Those mechanisms could reinforce each other, but their relationship need not be immediate or uniform across industries. Scenario adjudication must consequently use the declared economy-wide outcome criterion. A single unemployment reading, a market settlement or an isolated policy event would not independently identify which complete scenario occurred. Each would remain evidence for its own bounded forecast question until a separate scenario outcome was supplied.

## Risks and decisions

A contraction would warrant reassessing the central outlook. Decision makers could prepare contingent actions that depend on observable developments rather than a commitment to one narrative. For example, they might preserve flexibility in spending plans until the conditions relevant to their decision became clearer. A precaution of this kind would acknowledge uncertainty without asserting that the adverse scenario was inevitable or that its timing could be known precisely.

Evaluation should retain the original forecast probabilities and resolution criteria. Changing a probability after learning the outcome would obscure what was actually predicted. Likewise, an ambiguous observation should remain unresolved until evidence satisfies the specified contract. A later report could use recorded outcomes to describe the forecasting record, provided it kept scenario and binary scores separate and disclosed outstanding questions. A small set of scored forecasts would not support a broad claim of calibrated performance. Reliable interpretation would depend on the quality of the retained evidence as well as the arithmetic of each score.

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[70%] Baseline expansion**: NBER records no recession beginning before 2027-12-31.
- **[30%] Contraction**: NBER records a recession beginning before 2027-12-31.

### Official series to watch
| Series | Latest complete historical observation | Model threshold / period | Empirical base rate vs model P | Source |
|---|---|---|---|---|
| Unemployment Rate — United States (fred:UNRATE) | 4.2% (2026-09) | > 4% / 2027-06 | insufficient history vs model 70% | [Source](<https://fred.stlouisfed.org/series/UNRATE>) [S1] |
| Federal Funds Effective Rate — United States (fred:FEDFUNDS) | 3.5% (2026-09) | < 3% / 2027-12 | insufficient history vs model 40% | [Source](<https://fred.stlouisfed.org/series/FEDFUNDS>) [S2] |

<!-- forecast-track-record:start -->
## Historical forecasting track record

These scores describe retained forecasts with recorded outcomes. A limited record does not establish calibration.

| Forecast type | Forecasts | Resolved | Outstanding | Mean Brier |
|---|---:|---:|---:|---:|
| Scenarios (multiclass) | 0 | 0 | 0 | — |
| Market binaries | 0 | 0 | 0 | — |
| Official-data binaries | 0 | 0 | 0 | — |
| Unanchored binaries | 0 | 0 | 0 | — |

Scenario and binary scores have separate denominators. This report is excluded from its own history.
<!-- forecast-track-record:end -->

## References

1. [S1] Unemployment Rate — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/UNRATE](https://fred.stlouisfed.org/series/UNRATE)
2. [S2] Federal Funds Effective Rate — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/FEDFUNDS](https://fred.stlouisfed.org/series/FEDFUNDS)
