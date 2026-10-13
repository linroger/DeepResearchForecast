# Official data series catalog

Generated from `deerflow_bridge/data_catalog.py` by `render_catalog_files()`; do not edit by hand (regenerate with `python deerflow_bridge/data_catalog.py --write-markdown`).

323 curated series across 6 providers. Every id was verified live on 2026-10-12 or, when added later, on the day it was added: the provider returned recent data, and titles and units come from its own metadata. Pass an id exactly as written to `data_get`; `data_search` searches this catalog first. Read only the provider page you need; this index holds the id grammar.

Columns: Freq D/W/M/Q/A = daily/weekly/monthly/quarterly/annual; SA = seasonally adjusted, SAAR = seasonally adjusted annual rate, NSA = not seasonally adjusted, blank = not applicable or not published; Geo = ISO3 code, EMU = euro area, WLD = world or global benchmark. Daily series become monthly: averages, or end-of-period values for policy targets and debt stocks.

## Providers

| Provider | Source | Use for | Example id | Series | Page |
|---|---|---|---|---|---|
| fred | FRED (Federal Reserve Bank of St. Louis) | US macro, labor, prices, policy rates and the Treasury curve, credit spreads, dollar FX, energy prices, money; free-text search over about 800,000 series | `fred:UNRATE` | 83 | [catalog-fred.md](catalog-fred.md) |
| bls | U.S. Bureau of Labor Statistics | authoritative US CPI/PPI detail, average prices, payrolls, JOLTS, wages, ECI, productivity, state unemployment; no free-text search, use the catalog | `bls:CUUR0000SA0` | 45 | [catalog-bls.md](catalog-bls.md) |
| bis | Bank for International Settlements (BIS) | cross-country central bank policy rates, credit-to-GDP gaps, total credit, debt service ratios, property prices, USD and effective exchange rates, central bank assets | `bis:WS_CBPOL/M.US` | 50 | [catalog-bis.md](catalog-bis.md) |
| imf | International Monetary Fund (IMF) | primary commodity prices (oil, gas, metals incl. lithium and cobalt, food), CPI inflation by country, WEO world and euro-area aggregates and past WEO vintages; slow (30-60 s per call): prefer a listed faster equivalent, otherwise prefetch | `imf:PCPS/G001.POILBRE.USD.M` | 40 | [catalog-imf.md](catalog-imf.md) |
| wb | World Bank Data360 | annual cross-country history (World Development Indicators) and official projections: IMF WEO by country to 2031, World Bank Global Economic Prospects | `wb:IMF_WEO_NGDP_RPCH/CHN` | 54 | [catalog-wb.md](catalog-wb.md) |
| usgov | U.S. Government Open Data (Treasury Fiscal Data, USAspending, EIA, BEA) | federal debt to the penny, monthly receipts (customs duties, income taxes), outlays, gross interest and deficit, average interest rate on Treasury debt, Treasury reporting exchange rates, federal award spending | `usgov:treasury/mts_deficit` | 51 | [catalog-usgov.md](catalog-usgov.md) |

Keyed series (BEA_API_KEY, EIA_API_KEY): the us-gov server loads the EIA and BEA modules only when the key is set; without it `data_search` and the planner digest do not list them and `data_get` reports the provider unavailable. SEC company facts are not available through the supplied handler.

## Id grammar

- `fred:<FRED id>` — any FRED series id works, catalog or not.
- `bls:<BLS id>` — catalog ids only in practice (BLS has no search); keyless BLS allows 20 requests a day, so prefer the FRED mirror named in the notes.
- `wb:<INDICATOR>/<ISO3>` — Data360 databases WB_WDI, IMF_WEO, WB_GEP only; a `data_search` hit from another Data360 database is discovery metadata that `data_get` cannot fetch.
- `bis:<FLOW>/<KEY>` and `imf:<FLOW>/<KEY>` — key parts follow the dimension order below.
- `usgov:<recipe>[/<parameter>]` — recipes in [catalog-usgov.md](catalog-usgov.md).

### BIS dataflows

| Flow | Version | Key dimensions (in order) | Citation topic | Title |
|---|---|---|---|---|
| WS_CBPOL | 1.0 | FREQ.REF_AREA | CBPOL | Central bank policy rates |
| WS_CREDIT_GAP | 1.0 | FREQ.BORROWERS_CTY.TC_BORROWERS.TC_LENDERS.CG_DTYPE | CREDIT_GAPS | Credit-to-GDP gaps |
| WS_TC | 2.0 | FREQ.BORROWERS_CTY.TC_BORROWERS.TC_LENDERS.VALUATION.UNIT_TYPE.TC_ADJUST | TOTAL_CREDIT | Total credit |
| WS_DSR | 1.0 | FREQ.BORROWERS_CTY.DSR_BORROWERS | DSR | Debt service ratios |
| WS_SPP | 1.0 | FREQ.REF_AREA.VALUE.UNIT_MEASURE | RPP | Selected residential property prices |
| WS_XRU | 1.0 | FREQ.REF_AREA.CURRENCY.COLLECTION | XRU | US dollar exchange rates |
| WS_EER | 1.0 | FREQ.EER_TYPE.EER_BASKET.REF_AREA | EER | Effective exchange rates |
| WS_LONG_CPI | 1.0 | FREQ.REF_AREA.UNIT_MEASURE | CPI | Consumer prices statistics |
| WS_CBTA | 1.0 | FREQ.REF_AREA.COMP_METHOD.UNIT_MEASURE.CURRENCY.TRANSFORMATION | CBTA | Central bank total assets |
| WS_GLI | 1.0 | FREQ.CURR_DENOM.BORROWERS_CTY.BORROWERS_SECTOR.LENDERS_SECTOR.L_POS_TYPE.L_INSTR.UNIT_MEASURE | GLI | Global liquidity indicators |

### IMF dataflows

| Flow | Agency | Key dimensions (in order) | Title |
|---|---|---|---|
| WEO | IMF.RES | COUNTRY.INDICATOR.FREQUENCY | World Economic Outlook (WEO) |
| WEO_2026_APR_VINTAGE | IMF.RES | COUNTRY.INDICATOR.FREQUENCY | World Economic Outlook (WEO) 2026 April |
| WEO_2025_OCT_VINTAGE | IMF.RES | COUNTRY.INDICATOR.FREQUENCY | World Economic Outlook (WEO) 2025 October |
| PCPS | IMF.RES | COUNTRY.INDICATOR.DATA_TRANSFORMATION.FREQUENCY | Primary Commodity Price System (PCPS) |
| CPI | IMF.STA | COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY | Consumer Price Index (CPI) |

WEO vintages follow `WEO_<YYYY>_<APR|OCT>_VINTAGE` with the WEO key layout.

### usgov recipes

| Recipe | Parameter | Freq | Needs |
|---|---|---|---|
| `treasury/debt_to_penny` | — | D | — |
| `treasury/debt_held_public` | — | D | — |
| `treasury/mts_receipts` | — | M | — |
| `treasury/mts_outlays` | — | M | — |
| `treasury/mts_deficit` | — | M | — |
| `treasury/mts_customs_duties` | — | M | — |
| `treasury/mts_individual_income_taxes` | — | M | — |
| `treasury/mts_corporation_income_taxes` | — | M | — |
| `treasury/mts_interest_gross` | — | M | — |
| `treasury/avg_interest_rate` | <security_desc> | M | — |
| `treasury/fx` | <country_currency_desc> | Q | — |
| `spending/total` | — | A | — |
| `eia/electricity_sales` | <stateid>.<sectorid> | M | EIA_API_KEY |
| `eia/electricity_price` | <stateid>.<sectorid> | M | EIA_API_KEY |
| `eia/net_generation` | <fueltypeid> | M | EIA_API_KEY |
| `eia/crude_production` | — | M | EIA_API_KEY |
| `eia/generating_capacity` | <energysourceid> | A | EIA_API_KEY |
| `bea/real_gdp_growth` | — | Q | BEA_API_KEY |
| `bea/real_pce_growth` | — | Q | BEA_API_KEY |
| `bea/personal_income` | — | Q | BEA_API_KEY |
| `bea/nominal_pce` | — | Q | BEA_API_KEY |
| `bea/value_added_by_industry` | <BEA industry code> | Q | BEA_API_KEY |
