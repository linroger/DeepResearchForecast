# Source-preserving research

A **qualified** forecast: revenue is USD 1,250.50, downside **-12.5%**, conditional on demand. Do not treat this estimate as reported fact. See [official source](https://example.org/filing?year=2026&unit=USD), citation [S1], and footnote[^risk]. The `net_margin` variable is literal code.

## Records

| Item | 2025 Actual | 2026 Estimate | Qualification |
| :--- | ---: | ---: | :--- |
| Revenue | 1,100.00 | 1,250.50 | Assumes **5%** price growth |
| Loss | (12.50) | -9.25 | [Method](https://example.org/method) |
| Not available | | N/A | No reported observation |

3. First numbered condition.
   - A nested condition, **not guaranteed**.
4. Second numbered condition.

> Management guidance is conditional.
>
> A second paragraph remains part of the quote.

<!-- viz:charts/forecast.png -->
![Forecast paths; USD million, estimates](charts/forecast.png "Conditional forecast")

Source: supplied scenario chart. Values are illustrative; do not infer certainty.

```python
if revenue < 0:
    loss = -revenue
    print("USD", loss)
```

---

## References and disclosures

[S1] The filing is available at [the source page](https://example.org/filing?year=2026&unit=USD). Return to [Records](#records).

This material is conditional analysis. ~~Unqualified claim~~ has been withdrawn.

[^risk]: Outcomes depend on supply, financing and the demand assumption; losses may exceed **12.5%**.
