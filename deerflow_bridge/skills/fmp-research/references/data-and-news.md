# Choosing and interpreting financial evidence

Discover the relevant official MCP capability before calling it; the labels below describe information needs, not guaranteed MCP names.

| Question | Retrieve | Check before using |
|---|---|---|
| Which company/instrument? | Symbol/name search and company profile | Exchange, listing, legal entity, currency and identifiers |
| Is business growth/profitability changing? | Comparable income statements | Fiscal year/quarter, period length, revenue basis, exceptional items, filing/acceptance dates |
| Can the company fund its plans? | Balance sheet and cash flows | Stock versus flow, cash/debt definitions, capex sign, annual versus year-to-date cash flow |
| What expectations are priced in? | Relevant quote and analyst estimates | Quote timestamp/currency, estimate period, contributors if provided; forecasts are not outcomes |
| What changed recently? | Company/sector news plus primary filings/releases | Original publisher, article time, event time, duplicates and source access |
| What did management say? | Earnings transcript or filing | Speaker, call/report date, reported actuals versus forward guidance |

For a local listing and an ADR of the same issuer, separate each instrument's trading currency from the issuer's reporting currency. Verify the date-effective ADR ratio, share class and per-share denominator before comparing price, EPS, dividends or market capitalization. Two listings may return the same consolidated statements: reconcile their issuer identity and fiscal period, and never sum duplicate issuer financials. If ratio, currency or period metadata is missing, leave the dependent comparison unresolved while retaining supported qualitative findings.

For peer comparisons align accounting periods and currencies explicitly. Do not add annual and quarterly rows, sum year-to-date cash flow as if it were discrete quarters, or mix a point-in-time balance with a period flow. Negative capex and positive capex presentation conventions require inspecting actual fields before a free-cash-flow calculation. Do not assume all currencies are USD or all displayed percentages are fractions.

Reported financial statements are retrieved vendor representations of filings. FMP's [income statement](https://site.financialmodelingprep.com/developer/docs/stable/income-statement) and [balance sheet](https://site.financialmodelingprep.com/developer/docs/stable/balance-sheet-statement) pages describe those datasets. Retain filing links supplied by the response and consult the underlying filing for materially consequential definitions or discrepancies.

Analyst estimates describe projected revenue, EPS and other metrics; label them as analyst forecasts and retain their target period. Do not conflate a high/low analyst range with a calibrated probability interval. See [FMP financial estimates](https://site.financialmodelingprep.com/developer/docs/stable/financial-estimates).

News retrieval returns headlines/snippets with publisher links and ticker context. It does not prove the whole article was read. The [FMP stock-news documentation](https://site.financialmodelingprep.com/developer/docs/stable/stock-news) describes that feed. Follow original URLs using the normal web reader, retain dates, and attribute allegations, opinions and management claims to their sources.

## Useful bounded requests

- **Company outlook:** resolve the company, retrieve a few annual or quarterly periods covering the requested comparison, inspect balance-sheet/cash-flow constraints, and search a dated news window. Fetch primary sources for the changes most relevant to the forecast.
- **Earnings comparison:** retrieve the same fiscal period for each company, distinguish actuals from estimate snapshots, and obtain the release/transcript date. Do not compute a surprise from today's consensus unless it is demonstrably the pre-release estimate.
- **Sector developments:** identify the specific companies and driver, request limited relevant news, and corroborate with industry or official data. A list of large listed companies does not establish whole-sector coverage.

## Coverage and dates

Store retrieved_at separately from published_at, acceptedDate/filingDate, fiscal period and market timestamp. A filing date before a cutoff does not prove that the currently retrieved standardized row was unchanged since that date. Intraday prices, statements and estimates have different refresh schedules; consult [FMP cycle times](https://site.financialmodelingprep.com/developer/docs/cycle-times-stable) when freshness matters. Do not describe every endpoint as real time.

An omitted field is unknown; a permission error is not zero; a successful empty news page is not proof that no event occurred. Mark pagination or response truncation as incomplete coverage. Preserve fetched numeric values and native metadata exactly in the capture, then compute derived values separately with formulas and source references.
