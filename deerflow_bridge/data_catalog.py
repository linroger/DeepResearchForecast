"""Curated catalog of official data series for the research data tools.

WHY THIS MODULE EXISTS
----------------------
The six official-data providers (FRED, BLS, BIS, IMF, World Bank Data360
``wb`` and US Gov Open Data ``usgov``) expose hundreds of thousands of series,
but only FRED and Data360 have a usable free-text search, BLS has none at all,
the IMF server needs 30-50 s per call, and BIS/IMF ids are positional SDMX
keys that a model cannot guess.  This catalog is the deterministic map from a
forecasting concept ("US unemployment", "China GDP growth projection",
"失业率") to a canonical, fetchable series id (design.md §4, §5.1):

* ``CATALOG`` holds the curated :class:`CatalogEntry` rows.  Every id was
  verified live against the provider on ``VERIFIED_ON`` (data rows returned
  for a recent period; titles and units taken from the provider's own
  metadata).  Ids follow the agent-facing grammar ``<provider>:<native>``.
* ``BIS_FLOWS`` / ``IMF_FLOWS`` describe the SDMX dataflows the BIS and IMF
  ids use (version, ordered key dimensions, citation page); ``USGOV_RECIPES``
  describes the fixed Treasury / USAspending / SEC queries behind
  ``usgov:<recipe>`` ids, including the row keys that stop the Treasury API
  from silently summing rows.
* :func:`lookup`, :func:`search_catalog` and :func:`catalog_digest` are the
  deterministic helpers used by ``data_sources`` (search hits), the v3 planner
  (digest) and the skill reference (:func:`render_catalog_markdown`, the
  generator of ``skills/data-sources/references/series-catalog.md``).

Pure data plus small helpers: stdlib only, no I/O at import, so the module
imports in both the backend venv and the deer-flow venv.  Regenerate the skill
reference after editing the catalog::

    python deerflow_bridge/data_catalog.py --write-markdown
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "BIS_FLOWS",
    "CATALOG",
    "CatalogEntry",
    "FREQUENCIES",
    "FREQUENCY_LABELS",
    "IMF_FLOWS",
    "PROVIDERS",
    "SEASONAL_ADJUSTMENTS",
    "TOPICS",
    "USGOV_RECIPES",
    "VERIFIED_ON",
    "WB_DATABASES",
    "catalog_digest",
    "imf_flow_info",
    "lookup",
    "render_catalog_markdown",
    "resolve_usgov_recipe",
    "search_catalog",
    "wb_database",
]

VERIFIED_ON = "2026-10-11"

PROVIDERS: dict[str, dict[str, str]] = {
    "fred": {
        "name": "FRED (Federal Reserve Bank of St. Louis)",
        "role": ("US macro, labor, prices, policy rates and the Treasury curve, credit spreads, "
                 "dollar FX, energy prices, money; free-text search over about 800,000 series"),
        "example": "fred:UNRATE",
    },
    "bls": {
        "name": "U.S. Bureau of Labor Statistics",
        "role": ("authoritative US CPI/PPI detail, average prices, payrolls, JOLTS, wages, ECI, "
                 "productivity, state unemployment; no free-text search, use the catalog"),
        "example": "bls:CUUR0000SA0",
    },
    "bis": {
        "name": "Bank for International Settlements (BIS)",
        "role": ("cross-country central bank policy rates, credit-to-GDP gaps, total credit, "
                 "debt service ratios, property prices, USD and effective exchange rates, "
                 "central bank assets"),
        "example": "bis:WS_CBPOL/M.US",
    },
    "imf": {
        "name": "International Monetary Fund (IMF)",
        "role": ("primary commodity prices (oil, gas, metals incl. lithium and cobalt, food), "
                 "CPI inflation by country, WEO world and euro-area aggregates and past WEO "
                 "vintages; slow (30-50 s per call), best prefetched"),
        "example": "imf:PCPS/G001.POILBRE.USD.M",
    },
    "wb": {
        "name": "World Bank Data360",
        "role": ("annual cross-country history (World Development Indicators) and official "
                 "projections: IMF WEO by country to 2031, World Bank Global Economic Prospects"),
        "example": "wb:IMF_WEO_NGDP_RPCH/CHN",
    },
    "usgov": {
        "name": "U.S. Government Open Data (Treasury Fiscal Data, USAspending)",
        "role": ("federal debt to the penny, monthly receipts, outlays and deficit, average "
                 "interest rate on Treasury debt, Treasury reporting exchange rates, federal "
                 "award spending, SEC company facts"),
        "example": "usgov:treasury/mts_deficit",
    },
}

FREQUENCIES: tuple[str, ...] = ("D", "W", "M", "Q", "A")
FREQUENCY_LABELS: dict[str, str] = {
    "D": "daily", "W": "weekly", "M": "monthly", "Q": "quarterly", "A": "annual",
}
# "" means the provider publishes no adjustment flag or the concept does not apply
# (annual data, interest rates, exchange rates, year-over-year changes).
SEASONAL_ADJUSTMENTS: tuple[str, ...] = ("SA", "NSA", "SAAR", "")

# Topic vocabulary plus the query terms (EN + ZH) that trigger each topic.
TOPICS: dict[str, tuple[str, ...]] = {
    "growth": ("growth", "gdp", "economy", "economic", "recession", "output", "增长", "经济", "衰退"),
    "inflation": ("inflation", "cpi", "consumer prices", "deflation", "通胀", "物价", "通缩"),
    "labor": ("labor", "labour", "jobs", "employment", "unemployment", "wages", "就业", "失业", "工资"),
    "rates": ("interest rate", "rates", "yield", "bond", "利率", "收益率", "债券"),
    "credit": ("credit", "leverage", "spread", "debt service", "信贷", "杠杆", "利差"),
    "housing": ("housing", "home", "house", "property", "real estate", "mortgage",
                "房地产", "房价", "住房", "楼市"),
    "fx": ("exchange rate", "currency", "fx", "dollar", "汇率", "货币"),
    "energy": ("energy", "oil", "gas", "electricity", "power", "能源", "石油", "原油", "天然气", "电力"),
    "commodities": ("commodity", "commodities", "metal", "metals", "大宗商品", "金属"),
    "fiscal": ("fiscal", "budget", "deficit", "government debt", "public debt", "treasury",
               "财政", "赤字", "政府债务"),
    "trade": ("trade", "exports", "imports", "tariff", "tariffs", "贸易", "出口", "进口", "关税"),
    "money": ("money supply", "liquidity", "balance sheet", "流动性", "货币供应", "资产负债表"),
    "markets": ("stock", "stocks", "equity", "equities", "volatility", "股市", "股票", "波动"),
    "sentiment": ("sentiment", "confidence", "expectations", "信心", "预期"),
    "consumption": ("consumer spending", "consumption", "retail", "消费", "零售"),
    "production": ("industrial", "manufacturing", "production", "factory", "工业", "制造业", "生产"),
    "income": ("income", "saving", "savings", "收入", "储蓄"),
    "population": ("population", "demographic", "demographics", "人口"),
    "climate": ("emissions", "co2", "carbon", "climate", "排放", "碳", "气候"),
    "projections": ("forecast", "projection", "projections", "outlook", "预测", "展望"),
    "policy": ("central bank", "policy rate", "monetary policy", "央行", "货币政策"),
}

# Geography codes used by the catalog -> (English name, aliases EN + ZH) for query matching.
# "WLD" marks global benchmarks (commodity prices, world aggregates): neutral for country queries.
GEOGRAPHIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "USA": ("United States", ("united states", "america", "american", "usa", "federal reserve",
                              "fed", "fomc", "美国", "美联储")),
    "CHN": ("China", ("china", "chinese", "prc", "pboc", "中国", "人民银行", "人民币")),
    "EMU": ("Euro area", ("euro area", "eurozone", "euro zone", "europe", "european", "ecb",
                          "欧元区", "欧洲", "欧洲央行")),
    "JPN": ("Japan", ("japan", "japanese", "boj", "日本", "日本央行")),
    "GBR": ("United Kingdom", ("united kingdom", "britain", "british", "england", "boe",
                               "英国", "英格兰银行")),
    "DEU": ("Germany", ("germany", "german", "德国")),
    "IND": ("India", ("india", "indian", "rbi", "印度")),
    "BRA": ("Brazil", ("brazil", "brazilian", "巴西")),
    "CAN": ("Canada", ("canada", "canadian", "加拿大")),
    "KOR": ("Korea", ("korea", "korean", "south korea", "韩国")),
    "AUS": ("Australia", ("australia", "australian", "rba", "澳大利亚", "澳洲")),
    "CHE": ("Switzerland", ("switzerland", "swiss", "snb", "瑞士")),
    "MEX": ("Mexico", ("mexico", "mexican", "banxico", "墨西哥")),
    "WLD": ("World", ("world", "global", "worldwide", "全球", "世界")),
}

# BIS SDMX dataflows used by bis:<FLOW>/<KEY> ids.  dims = key dimensions in order
# (verified with the BIS structure API); topic = data.bis.org citation topic slug.
BIS_FLOWS: dict[str, dict[str, Any]] = {
    "WS_CBPOL": {"version": "1.0", "dims": ("FREQ", "REF_AREA"), "topic": "CBPOL",
                 "title": "Central bank policy rates"},
    "WS_CREDIT_GAP": {"version": "1.0",
                      "dims": ("FREQ", "BORROWERS_CTY", "TC_BORROWERS", "TC_LENDERS", "CG_DTYPE"),
                      "topic": "CREDIT_GAPS", "title": "Credit-to-GDP gaps"},
    "WS_TC": {"version": "2.0",
              "dims": ("FREQ", "BORROWERS_CTY", "TC_BORROWERS", "TC_LENDERS", "VALUATION",
                       "UNIT_TYPE", "TC_ADJUST"),
              "topic": "TOTAL_CREDIT", "title": "Total credit"},
    "WS_DSR": {"version": "1.0", "dims": ("FREQ", "BORROWERS_CTY", "DSR_BORROWERS"), "topic": "DSR",
               "title": "Debt service ratios"},
    "WS_SPP": {"version": "1.0", "dims": ("FREQ", "REF_AREA", "VALUE", "UNIT_MEASURE"), "topic": "RPP",
               "title": "Selected residential property prices"},
    "WS_XRU": {"version": "1.0", "dims": ("FREQ", "REF_AREA", "CURRENCY", "COLLECTION"), "topic": "XRU",
               "title": "US dollar exchange rates"},
    "WS_EER": {"version": "1.0", "dims": ("FREQ", "EER_TYPE", "EER_BASKET", "REF_AREA"), "topic": "EER",
               "title": "Effective exchange rates"},
    "WS_LONG_CPI": {"version": "1.0", "dims": ("FREQ", "REF_AREA", "UNIT_MEASURE"), "topic": "CPI",
                    "title": "Consumer prices statistics"},
    "WS_CBTA": {"version": "1.0",
                "dims": ("FREQ", "REF_AREA", "COMP_METHOD", "UNIT_MEASURE", "CURRENCY", "TRANSFORMATION"),
                "topic": "CBTA", "title": "Central bank total assets"},
    "WS_GLI": {"version": "1.0",
               "dims": ("FREQ", "CURR_DENOM", "BORROWERS_CTY", "BORROWERS_SECTOR", "LENDERS_SECTOR",
                        "L_POS_TYPE", "L_INSTR", "UNIT_MEASURE"),
               "topic": "GLI", "title": "Global liquidity indicators"},
}

# IMF SDMX 3.0 dataflows used by imf:<FLOW>/<KEY> ids.  base_flow = the flow whose
# data.imf.org page is cited (vintage flows have no page of their own).
_WEO_DIMS = ("COUNTRY", "INDICATOR", "FREQUENCY")
IMF_FLOWS: dict[str, dict[str, Any]] = {
    "WEO": {"agency": "IMF.RES", "dims": _WEO_DIMS, "base_flow": "WEO",
            "title": "World Economic Outlook (WEO)"},
    "WEO_2026_APR_VINTAGE": {"agency": "IMF.RES", "dims": _WEO_DIMS, "base_flow": "WEO",
                             "title": "World Economic Outlook (WEO) 2026 April"},
    "WEO_2025_OCT_VINTAGE": {"agency": "IMF.RES", "dims": _WEO_DIMS, "base_flow": "WEO",
                             "title": "World Economic Outlook (WEO) 2025 October"},
    "PCPS": {"agency": "IMF.RES", "dims": ("COUNTRY", "INDICATOR", "DATA_TRANSFORMATION", "FREQUENCY"),
             "base_flow": "PCPS", "title": "Primary Commodity Price System (PCPS)"},
    "CPI": {"agency": "IMF.STA",
            "dims": ("COUNTRY", "INDEX_TYPE", "COICOP_1999", "TYPE_OF_TRANSFORMATION", "FREQUENCY"),
            "base_flow": "CPI", "title": "Consumer Price Index (CPI)"},
}
_WEO_VINTAGE_RE = re.compile(r"^WEO_(\d{4})_(APR|OCT)_VINTAGE$")
_VINTAGE_MONTHS = {"APR": "April", "OCT": "October"}

# World Bank Data360 databases reachable through wb:<INDICATOR>/<ISO3> ids; the
# database is the indicator's first two underscore-separated parts.
WB_DATABASES: tuple[str, ...] = ("WB_WDI", "IMF_WEO", "WB_GEP")

_TREASURY_API = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
_MTS_FIELDS = "record_date,line_code_nbr,src_line_nbr,classification_desc,current_month_rcpt_outly_amt"
_MTS_NOTE = ("MTS Table 3 row selected by line_code_nbr (stable; src_line_nbr drifts between years). "
             "Strong monthly seasonality (April and September receipts); compare with the same month a "
             "year earlier or use fiscal-year-to-date totals.")

# usgov:<recipe>[/<param>] -> fixed query.  Treasury recipes call the usgov MCP tool
# treasury_query_fiscal_data with endpoint/fields/filters/sort (callers append
# "record_date:gte:<start>" to filters and choose page_size); fields always include the
# row key so the Fiscal Data API never sums rows that share the selected columns.
# param_field: the id suffix becomes "<param_field>:eq:<param>" (appended to filters).
# tiebreak_field: rows sharing a date are amendments -- keep the smallest tiebreak value.
USGOV_RECIPES: dict[str, dict[str, Any]] = {
    "treasury/debt_to_penny": {
        "title": "Debt to the Penny: Total Public Debt Outstanding",
        "title_zh": "美国联邦公共债务总额（每日）",
        "tool": "treasury_query_fiscal_data",
        "tool_args": {},
        "endpoint": "/v2/accounting/od/debt_to_penny",
        "api_url": f"{_TREASURY_API}/v2/accounting/od/debt_to_penny",
        "fields": "record_date,tot_pub_debt_out_amt",
        "filters": "",
        "sort": "-record_date",
        "date_field": "record_date",
        "value_field": "tot_pub_debt_out_amt",
        "param_field": "",
        "param_format": "",
        "param_examples": (),
        "tiebreak_field": "",
        "frequency": "D",
        "seasonal_adjustment": "",
        "units": "U.S. dollars",
        "source_url": "https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/",
        "notes": "Business-day series; includes intragovernmental holdings (use debt_held_public for market debt).",
    },
    "treasury/debt_held_public": {
        "title": "Debt to the Penny: Debt Held by the Public",
        "title_zh": "美国公众持有的联邦债务（每日）",
        "tool": "treasury_query_fiscal_data",
        "tool_args": {},
        "endpoint": "/v2/accounting/od/debt_to_penny",
        "api_url": f"{_TREASURY_API}/v2/accounting/od/debt_to_penny",
        "fields": "record_date,debt_held_public_amt",
        "filters": "",
        "sort": "-record_date",
        "date_field": "record_date",
        "value_field": "debt_held_public_amt",
        "param_field": "",
        "param_format": "",
        "param_examples": (),
        "tiebreak_field": "",
        "frequency": "D",
        "seasonal_adjustment": "",
        "units": "U.S. dollars",
        "source_url": "https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/",
        "notes": "Excludes intragovernmental holdings such as the Social Security trust funds.",
    },
    "treasury/mts_receipts": {
        "title": "Monthly Treasury Statement: Total Receipts (current month)",
        "title_zh": "美国联邦财政月度总收入",
        "tool": "treasury_query_fiscal_data",
        "tool_args": {},
        "endpoint": "/v1/accounting/mts/mts_table_3",
        "api_url": f"{_TREASURY_API}/v1/accounting/mts/mts_table_3",
        "fields": _MTS_FIELDS,
        "filters": "line_code_nbr:eq:130",
        "sort": "-record_date",
        "date_field": "record_date",
        "value_field": "current_month_rcpt_outly_amt",
        "param_field": "",
        "param_format": "",
        "param_examples": (),
        "tiebreak_field": "",
        "frequency": "M",
        "seasonal_adjustment": "NSA",
        "units": "U.S. dollars",
        "source_url": "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/",
        "notes": _MTS_NOTE,
    },
    "treasury/mts_outlays": {
        "title": "Monthly Treasury Statement: Total Outlays (current month)",
        "title_zh": "美国联邦财政月度总支出",
        "tool": "treasury_query_fiscal_data",
        "tool_args": {},
        "endpoint": "/v1/accounting/mts/mts_table_3",
        "api_url": f"{_TREASURY_API}/v1/accounting/mts/mts_table_3",
        "fields": _MTS_FIELDS,
        "filters": "line_code_nbr:eq:490",
        "sort": "-record_date",
        "date_field": "record_date",
        "value_field": "current_month_rcpt_outly_amt",
        "param_field": "",
        "param_format": "",
        "param_examples": (),
        "tiebreak_field": "",
        "frequency": "M",
        "seasonal_adjustment": "NSA",
        "units": "U.S. dollars",
        "source_url": "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/",
        "notes": _MTS_NOTE,
    },
    "treasury/mts_deficit": {
        "title": "Monthly Treasury Statement: Surplus (+) or Deficit (-) (current month)",
        "title_zh": "美国联邦财政月度盈余（+）或赤字（-）",
        "tool": "treasury_query_fiscal_data",
        "tool_args": {},
        "endpoint": "/v1/accounting/mts/mts_table_3",
        "api_url": f"{_TREASURY_API}/v1/accounting/mts/mts_table_3",
        "fields": _MTS_FIELDS,
        "filters": "line_code_nbr:eq:520",
        "sort": "-record_date",
        "date_field": "record_date",
        "value_field": "current_month_rcpt_outly_amt",
        "param_field": "",
        "param_format": "",
        "param_examples": (),
        "tiebreak_field": "",
        "frequency": "M",
        "seasonal_adjustment": "NSA",
        "units": "U.S. dollars",
        "source_url": "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/",
        "notes": "Negative values are deficits. " + _MTS_NOTE,
    },
    "treasury/avg_interest_rate": {
        "title": "Average Interest Rates on U.S. Treasury Securities",
        "title_zh": "美国国债平均利率",
        "tool": "treasury_query_fiscal_data",
        "tool_args": {},
        "endpoint": "/v2/accounting/od/avg_interest_rates",
        "api_url": f"{_TREASURY_API}/v2/accounting/od/avg_interest_rates",
        "fields": "record_date,security_type_desc,security_desc,avg_interest_rate_amt",
        "filters": "",
        "sort": "-record_date",
        "date_field": "record_date",
        "value_field": "avg_interest_rate_amt",
        "param_field": "security_desc",
        "param_format": "<security_desc>",
        "param_examples": ("Treasury Bills", "Treasury Notes", "Treasury Bonds",
                           "Treasury Inflation-Protected Securities (TIPS)", "Total Marketable",
                           "Total Interest-bearing Debt"),
        "tiebreak_field": "",
        "frequency": "M",
        "seasonal_adjustment": "",
        "units": "Percent",
        "source_url": "https://fiscaldata.treasury.gov/datasets/average-interest-rates-treasury-securities/",
        "notes": "Average rate on outstanding debt (a slow-moving cost of debt), not a market yield.",
    },
    "treasury/fx": {
        "title": "Treasury Reporting Rates of Exchange",
        "title_zh": "美国财政部报告汇率",
        "tool": "treasury_query_fiscal_data",
        "tool_args": {},
        "endpoint": "/v1/accounting/od/rates_of_exchange",
        "api_url": f"{_TREASURY_API}/v1/accounting/od/rates_of_exchange",
        "fields": "record_date,country_currency_desc,exchange_rate,effective_date",
        "filters": "",
        "sort": "-record_date",
        "date_field": "record_date",
        "value_field": "exchange_rate",
        "param_field": "country_currency_desc",
        "param_format": "<country_currency_desc>",
        "param_examples": ("Euro Zone-Euro", "China-Renminbi", "Japan-Yen", "United Kingdom-Pound",
                           "Canada-Dollar", "Mexico-Peso", "India-Rupee"),
        "tiebreak_field": "effective_date",
        "frequency": "Q",
        "seasonal_adjustment": "",
        "units": "Foreign currency units per U.S. dollar",
        "source_url": "https://fiscaldata.treasury.gov/datasets/treasury-reporting-rates-exchange/",
        "notes": ("Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter "
                  "amendment (later effective_date); the quarter-end rate is the earliest effective_date."),
    },
    "spending/total": {
        "title": "USAspending: Federal Award Spending by Fiscal Year",
        "title_zh": "美国联邦奖励支出（按财年）",
        "tool": "usa_spending_over_time",
        "tool_args": {"group": "fiscal_year"},
        "endpoint": "https://api.usaspending.gov/api/v2/search/spending_over_time/",
        "api_url": "https://api.usaspending.gov/api/v2/search/spending_over_time/",
        "fields": "",
        "filters": "",
        "sort": "",
        "date_field": "periodStart",
        "value_field": "amount",
        "param_field": "",
        "param_format": "",
        "param_examples": (),
        "tiebreak_field": "",
        "frequency": "A",
        "seasonal_adjustment": "",
        "units": "U.S. dollars",
        "source_url": "https://www.usaspending.gov/explorer",
        "notes": ("Award obligations (contracts, grants, loans, direct payments), not total budget outlays; "
                  "periodStart is the first month of the fiscal year (FY2025 starts 2024-10). Recent years "
                  "rise as agencies report late."),
    },
    "sec": {
        "title": "SEC XBRL company concept (company facts)",
        "title_zh": "SEC公司财务数据（XBRL概念）",
        "tool": "sec_company_concept",
        "tool_args": {},
        "endpoint": "https://data.sec.gov/api/xbrl/companyconcept/",
        "api_url": "https://data.sec.gov/api/xbrl/companyconcept/",
        "fields": "",
        "filters": "",
        "sort": "",
        "date_field": "period",
        "value_field": "value",
        "param_field": "",
        "param_format": "<CIK or ticker>/<us-gaap concept>",
        "param_examples": ("AAPL/RevenueFromContractWithCustomerExcludingAssessedTax",),
        "tiebreak_field": "filed",
        "frequency": "A",
        "seasonal_adjustment": "",
        "units": "U.S. dollars",
        "source_url": "https://www.sec.gov/edgar/search/",
        "notes": ("Template, not a catalog series. Annual facts repeat across later filings (keep the latest "
                  "filed per period) and include quarterly comparatives; companies switch concepts "
                  "(Apple stopped tagging Revenues after FY2018)."),
    },
}


@dataclass(frozen=True)
class CatalogEntry:
    series: str              # canonical fetchable id, e.g. "fred:UNRATE"
    title: str               # official title (English)
    title_zh: str            # Chinese title
    units: str               # official units, incl. index base
    frequency: str           # "D"|"W"|"M"|"Q"|"A"
    seasonal_adjustment: str  # "SA"|"NSA"|"SAAR"|""
    geography: str           # ISO3 or "WLD"/"EMU"
    topics: tuple[str, ...]
    keywords: tuple[str, ...]  # lowercase EN + ZH search terms
    notes: str = ""          # pitfalls
    source_url: str = ""     # human citation page

    @property
    def provider(self) -> str:
        return self.series.split(":", 1)[0]

    @property
    def native(self) -> str:
        return self.series.split(":", 1)[1]


# ---------------------------------------------------------------------------
# Entry constructors (derive ids and citation pages from the provider patterns)
# ---------------------------------------------------------------------------

def _entry(provider: str, native: str, title: str, title_zh: str, units: str, frequency: str,
           sa: str, geography: str, topics: tuple[str, ...], keywords: tuple[str, ...],
           notes: str, source_url: str) -> CatalogEntry:
    cleaned: list[str] = []
    for keyword in keywords:
        norm = " ".join(keyword.lower().split())
        if norm and norm not in cleaned:
            cleaned.append(norm)
    return CatalogEntry(series=f"{provider}:{native}", title=title, title_zh=title_zh, units=units,
                        frequency=frequency, seasonal_adjustment=sa, geography=geography,
                        topics=tuple(topics), keywords=tuple(cleaned), notes=notes,
                        source_url=source_url)


def _fred(sid: str, title: str, title_zh: str, units: str, frequency: str, sa: str,
          topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "",
          geography: str = "USA") -> CatalogEntry:
    return _entry("fred", sid, title, title_zh, units, frequency, sa, geography, topics, keywords,
                  notes, f"https://fred.stlouisfed.org/series/{sid}")


def _bls(sid: str, title: str, title_zh: str, units: str, frequency: str, sa: str,
         topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "") -> CatalogEntry:
    return _entry("bls", sid, title, title_zh, units, frequency, sa, "USA", topics, keywords,
                  notes, f"https://data.bls.gov/timeseries/{sid}")


def _bis(flow: str, key: str, title: str, title_zh: str, units: str, geography: str,
         topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "") -> CatalogEntry:
    meta = BIS_FLOWS[flow]
    url = f"https://data.bis.org/topics/{meta['topic']}/BIS,{flow},{meta['version']}/{key}"
    return _entry("bis", f"{flow}/{key}", title, title_zh, units, key.split(".", 1)[0], "",
                  geography, topics, keywords, notes, url)


def _imf(flow: str, key: str, title: str, title_zh: str, units: str, geography: str,
         topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "") -> CatalogEntry:
    meta = IMF_FLOWS[flow]
    url = f"https://data.imf.org/en/datasets/{meta['agency']}:{meta['base_flow']}"
    return _entry("imf", f"{flow}/{key}", title, title_zh, units, key.rsplit(".", 1)[1], "",
                  geography, topics, keywords, notes, url)


def _wb(indicator: str, iso3: str, title: str, title_zh: str, units: str,
        topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "") -> CatalogEntry:
    return _entry("wb", f"{indicator}/{iso3}", title, title_zh, units, "A", "", iso3, topics, keywords,
                  notes, f"https://data360.worldbank.org/en/indicator/{indicator}")


def _usgov(recipe_id: str, topics: tuple[str, ...], keywords: tuple[str, ...],
           title_suffix: str = "", title_zh: str = "", notes: str = "",
           geography: str = "USA") -> CatalogEntry:
    resolved = resolve_usgov_recipe(recipe_id)
    if resolved is None:
        raise ValueError(f"unknown usgov recipe id: {recipe_id}")
    _key, recipe, _param = resolved
    title = recipe["title"] + (f": {title_suffix}" if title_suffix else "")
    return _entry("usgov", recipe_id, title, title_zh or recipe["title_zh"], recipe["units"],
                  recipe["frequency"], recipe["seasonal_adjustment"], geography, topics, keywords,
                  notes or recipe["notes"], recipe["source_url"])


def resolve_usgov_recipe(native: str) -> tuple[str, dict[str, Any], str] | None:
    """``"treasury/fx/Japan-Yen"`` -> ``("treasury/fx", recipe, "Japan-Yen")``.

    Recipe keys match case-insensitively; the parameter keeps its case (Treasury
    filters are case-sensitive).  Returns None for an unknown recipe, a missing
    parameter, or a parameter given to a recipe that takes none.
    """
    text = (native or "").strip().strip("/")
    lowered = text.lower()
    for key in sorted(USGOV_RECIPES, key=len, reverse=True):
        recipe = USGOV_RECIPES[key]
        takes_param = bool(recipe["param_format"])
        if lowered == key:
            return None if takes_param else (key, recipe, "")
        if lowered.startswith(key + "/"):
            param = text[len(key) + 1:].strip()
            if not takes_param or not param:
                return None
            if key == "sec":
                parts = param.split("/")
                if len(parts) != 2 or not all(part.strip() for part in parts):
                    return None
            return key, recipe, param
    return None


def imf_flow_info(flow: str) -> dict[str, Any] | None:
    """IMF_FLOWS row for ``flow``; WEO vintages not listed (e.g. a newer
    ``WEO_2026_OCT_VINTAGE``) get the WEO vintage layout.  None when unknown."""
    name = (flow or "").strip().upper()
    if name in IMF_FLOWS:
        return dict(IMF_FLOWS[name])
    match = _WEO_VINTAGE_RE.match(name)
    if match is None:
        return None
    return {"agency": "IMF.RES", "dims": _WEO_DIMS, "base_flow": "WEO",
            "title": f"World Economic Outlook (WEO) {match.group(1)} {_VINTAGE_MONTHS[match.group(2)]}"}


def wb_database(indicator: str) -> str | None:
    """Data360 database of a ``wb:`` indicator id (``IMF_WEO_NGDP_RPCH`` -> ``IMF_WEO``)."""
    parts = (indicator or "").strip().upper().split("_")
    if len(parts) < 3:
        return None
    database = "_".join(parts[:2])
    return database if database in WB_DATABASES else None


# ---------------------------------------------------------------------------
# FRED (Federal Reserve Bank of St. Louis)
# ---------------------------------------------------------------------------

_ICE_NOTE = "ICE BofA indices on FRED keep only about three years of daily history (licensing)."
_FX_NOTE = "Noon buying rates in New York; weekly/daily moves are noisy, compare monthly averages."

_FRED_ENTRIES: tuple[CatalogEntry, ...] = (
    # Output and activity
    _fred("A191RL1Q225SBEA", "Real Gross Domestic Product", "美国实际GDP增长率（环比折年率）",
          "Percent Change from Preceding Period", "Q", "SAAR", ("growth",),
          ("gdp growth", "real gdp growth", "economic growth", "growth rate", "quarterly gdp", "recession",
           "gdp增长", "gdp增速", "经济增长", "增长率", "经济衰退"),
          "Quarter-on-quarter change at a seasonally adjusted annual rate, not year-over-year; "
          "advance estimates are revised twice."),
    _fred("GDPC1", "Real Gross Domestic Product", "美国实际国内生产总值",
          "Billions of Chained 2017 Dollars", "Q", "SAAR", ("growth",),
          ("real gdp", "gdp level", "economic output", "gross domestic product", "实际gdp", "国内生产总值"),
          "Level in chained 2017 dollars; use transform yoy for year-over-year growth."),
    _fred("GDP", "Gross Domestic Product", "美国名义国内生产总值", "Billions of Dollars", "Q", "SAAR",
          ("growth",), ("nominal gdp", "gdp", "gross domestic product", "名义gdp", "国内生产总值"),
          "Current dollars; use GDPC1 for real output."),
    _fred("INDPRO", "Industrial Production: Total Index", "美国工业生产指数", "Index 2017=100", "M", "SA",
          ("production",), ("industrial production", "factory output", "manufacturing output", "工业生产",
                            "工业产出")),
    _fred("TCU", "Capacity Utilization: Total Index", "美国产能利用率", "Percent", "M", "SA",
          ("production",), ("capacity utilization", "spare capacity", "产能利用率")),
    _fred("RSAFS", "Advance Retail Sales: Retail Trade and Food Services", "美国零售和餐饮销售额",
          "Millions of Dollars", "M", "SA", ("consumption",),
          ("retail sales", "consumer spending", "零售销售", "零售额"),
          "Advance estimate in nominal dollars; revised in the following two months."),
    _fred("RRSFS", "Advance Real Retail and Food Services Sales", "美国实际零售和餐饮销售额",
          "Millions of 1982-84 CPI Adjusted Dollars", "M", "SA", ("consumption",),
          ("real retail sales", "inflation-adjusted retail sales", "实际零售销售")),
    _fred("PCEC96", "Real Personal Consumption Expenditures", "美国实际个人消费支出",
          "Billions of Chained 2017 Dollars", "M", "SAAR", ("consumption",),
          ("personal consumption", "consumer spending", "real consumption", "个人消费支出", "居民消费")),
    _fred("DSPIC96", "Real Disposable Personal Income", "美国实际个人可支配收入",
          "Billions of Chained 2017 Dollars", "M", "SAAR", ("income",),
          ("disposable income", "household income", "real income", "可支配收入", "居民收入")),
    _fred("PSAVERT", "Personal Saving Rate", "美国个人储蓄率", "Percent", "M", "SAAR", ("income",),
          ("saving rate", "savings rate", "household saving", "储蓄率")),
    _fred("TOTALSA", "Total Vehicle Sales", "美国汽车总销量", "Millions of Units", "M", "SAAR",
          ("consumption",), ("vehicle sales", "car sales", "auto sales", "light vehicle sales", "汽车销量")),
    # Housing
    _fred("HOUST", "New Privately-Owned Housing Units Started: Total Units", "美国新屋开工",
          "Thousands of Units", "M", "SAAR", ("housing",),
          ("housing starts", "home construction", "residential construction", "新屋开工", "住房开工")),
    _fred("PERMIT", "New Privately-Owned Housing Units Authorized in Permit-Issuing Places: Total Units",
          "美国新屋营建许可", "Thousands of Units", "M", "SAAR", ("housing",),
          ("building permits", "housing permits", "营建许可", "建筑许可")),
    _fred("CSUSHPISA", "S&P Cotality Case-Shiller U.S. National Home Price Index",
          "标普凯斯-席勒美国全国房价指数", "Index Jan 2000=100", "M", "SA", ("housing",),
          ("home prices", "house prices", "case-shiller", "housing prices", "房价", "房价指数"),
          "Published with a two-month lag (three-month moving average)."),
    _fred("MSPUS", "Median Sales Price of New Houses Sold for the United States", "美国新房销售价格中位数",
          "Dollars", "Q", "NSA", ("housing",),
          ("median home price", "median house price", "new home price", "房价中位数", "新房价格")),
    # Sentiment, money, financial conditions
    _fred("UMCSENT", "University of Michigan: Consumer Sentiment", "密歇根大学消费者信心指数",
          "Index 1966:Q1=100", "M", "NSA", ("sentiment",),
          ("consumer sentiment", "consumer confidence", "michigan sentiment", "消费者信心", "消费者情绪")),
    _fred("MICH", "University of Michigan: Inflation Expectation", "密歇根大学一年期通胀预期",
          "Percent", "M", "NSA", ("inflation", "sentiment"),
          ("inflation expectations", "consumer inflation expectations", "michigan inflation", "通胀预期"),
          "Median expected price change over the next 12 months."),
    _fred("M2SL", "M2", "美国M2货币供应量", "Billions of Dollars", "M", "SA", ("money",),
          ("m2", "money supply", "broad money", "货币供应", "广义货币")),
    _fred("WALCL", "Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level",
          "美联储资产负债表总资产", "Millions of U.S. Dollars", "W", "NSA", ("money", "policy"),
          ("fed balance sheet", "quantitative easing", "quantitative tightening", "qe", "qt",
           "美联储资产负债表", "缩表", "量化宽松")),
    _fred("RECPROUSM156N", "Smoothed U.S. Recession Probabilities", "美国衰退概率（平滑）", "Percent", "M",
          "NSA", ("growth",), ("recession probability", "recession odds", "recession risk", "衰退概率"),
          "Model estimate published with a lag of about two months."),
    _fred("NFCI", "Chicago Fed National Financial Conditions Index", "芝加哥联储全国金融状况指数", "Index",
          "W", "NSA", ("markets", "credit"),
          ("financial conditions", "financial stress", "nfci", "金融状况", "金融条件"),
          "Zero is average; positive values mean tighter than average conditions."),
    # Prices
    _fred("CPIAUCSL", "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
          "美国消费者价格指数（CPI-U，全部项目）", "Index 1982-1984=100", "M", "SA", ("inflation",),
          ("cpi", "inflation", "consumer prices", "consumer price index", "headline inflation", "cost of living",
           "通胀", "通货膨胀", "消费者价格指数", "物价"),
          "Index level: use transform yoy for the inflation rate. Headline YoY as published uses the NSA "
          "series bls:CUUR0000SA0. October 2025 is missing (2025 federal shutdown)."),
    _fred("CPILFESL",
          "Consumer Price Index for All Urban Consumers: All Items Less Food and Energy in U.S. City Average",
          "美国核心CPI（剔除食品和能源）", "Index 1982-1984=100", "M", "SA", ("inflation",),
          ("core cpi", "core inflation", "underlying inflation", "核心cpi", "核心通胀"),
          "Index level: use transform yoy for the core inflation rate."),
    _fred("PCEPI", "Personal Consumption Expenditures: Chain-type Price Index", "美国个人消费支出价格指数",
          "Index 2017=100", "M", "SA", ("inflation",),
          ("pce", "pce inflation", "pce price index", "inflation", "个人消费支出价格指数", "pce通胀"),
          "Index level: use transform yoy for PCE inflation."),
    _fred("PCEPILFE", "Personal Consumption Expenditures Excluding Food and Energy (Chain-Type Price Index)",
          "美国核心PCE价格指数", "Index 2017=100", "M", "SA", ("inflation",),
          ("core pce", "core inflation", "fed inflation target", "核心pce", "核心通胀"),
          "The Federal Reserve's 2 percent target is defined on PCE inflation; use transform yoy."),
    # Labor
    _fred("UNRATE", "Unemployment Rate", "美国失业率", "Percent", "M", "SA", ("labor",),
          ("unemployment", "unemployment rate", "jobless rate", "jobless", "labor market",
           "失业率", "失业", "就业市场"),
          "October 2025 is missing (2025 federal shutdown); BLS source series bls:LNS14000000."),
    _fred("U6RATE",
          "Total Unemployed, Plus All Persons Marginally Attached to the Labor Force, Plus Total Employed "
          "Part Time for Economic Reasons, as a Percent of the Civilian Labor Force Plus All Persons "
          "Marginally Attached to the Labor Force (U-6)",
          "美国U-6广义失业率", "Percent", "M", "SA", ("labor",),
          ("u-6", "u6", "underemployment", "broad unemployment", "广义失业率", "就业不足")),
    _fred("PAYEMS", "All Employees, Total Nonfarm", "美国非农就业人数", "Thousands of Persons", "M", "SA",
          ("labor",), ("nonfarm payrolls", "payrolls", "jobs", "employment", "job growth", "nfp",
                       "非农就业", "非农", "就业人数"),
          "Level in thousands; monthly job gains are the first difference. Benchmark revisions each February."),
    _fred("ICSA", "Initial Claims", "美国首次申请失业救济人数", "Number", "W", "SA", ("labor",),
          ("jobless claims", "initial claims", "unemployment claims", "layoffs", "初请失业金", "首次申请失业救济")),
    _fred("CCSA", "Continued Claims (Insured Unemployment)", "美国持续申请失业救济人数", "Number", "W", "SA",
          ("labor",), ("continuing claims", "insured unemployment", "续请失业金")),
    _fred("CIVPART", "Labor Force Participation Rate", "美国劳动参与率", "Percent", "M", "SA", ("labor",),
          ("participation rate", "labor force participation", "劳动参与率")),
    _fred("JTSJOL", "Job Openings: Total Nonfarm", "美国职位空缺数（JOLTS）", "Level in Thousands", "M", "SA",
          ("labor",), ("job openings", "jolts", "vacancies", "labor demand", "职位空缺", "岗位空缺")),
    _fred("CES0500000003", "Average Hourly Earnings of All Employees, Total Private", "美国私营部门平均时薪",
          "Dollars per Hour", "M", "SA", ("labor", "income"),
          ("average hourly earnings", "wages", "wage growth", "pay", "平均时薪", "工资增长", "薪资")),
    _fred("SAHMREALTIME", "Real-time Sahm Rule Recession Indicator", "萨姆规则衰退指标（实时）",
          "Percentage Points", "M", "SA", ("labor", "growth"),
          ("sahm rule", "recession indicator", "recession signal", "萨姆规则", "衰退信号"),
          "Signals a recession when the value reaches 0.50 percentage points."),
    # Policy rates, Treasury curve, inflation compensation
    _fred("FEDFUNDS", "Federal Funds Effective Rate", "联邦基金有效利率（月均）", "Percent", "M", "NSA",
          ("rates", "policy"),
          ("fed funds rate", "federal funds rate", "policy rate", "interest rate", "rate cut", "rate hike",
           "联邦基金利率", "美联储利率", "政策利率", "降息", "加息"),
          "Monthly average of the daily effective rate; the FOMC target range upper limit is fred:DFEDTARU."),
    _fred("DFF", "Federal Funds Effective Rate", "联邦基金有效利率（日度）", "Percent", "D", "NSA",
          ("rates", "policy"), ("daily fed funds", "effective federal funds rate", "联邦基金利率"),
          "Seven-day daily series (weekends carry the prior business day)."),
    _fred("DFEDTARU", "Federal Funds Target Range - Upper Limit", "联邦基金目标利率区间上限", "Percent", "D",
          "NSA", ("rates", "policy"),
          ("fed target rate", "target range", "fomc decision", "rate cut", "rate hike", "policy rate",
           "目标利率", "降息", "加息"),
          "Step series that changes only at FOMC decisions; the lower limit is 25 basis points below."),
    _fred("SOFR", "Secured Overnight Financing Rate", "有担保隔夜融资利率", "Percent", "D", "NSA", ("rates",),
          ("sofr", "overnight rate", "repo rate", "隔夜融资利率")),
    _fred("DGS3MO",
          "Market Yield on U.S. Treasury Securities at 3-Month Constant Maturity, Quoted on an Investment Basis",
          "美国3个月期国债收益率", "Percent", "D", "NSA", ("rates",),
          ("3-month treasury", "t-bill yield", "short-term rate", "3个月国债收益率", "短期国债")),
    _fred("DGS2",
          "Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity, Quoted on an Investment Basis",
          "美国2年期国债收益率", "Percent", "D", "NSA", ("rates",),
          ("2-year treasury", "2-year yield", "two-year yield", "2年期国债收益率")),
    _fred("DGS10",
          "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis",
          "美国10年期国债收益率", "Percent", "D", "NSA", ("rates",),
          ("10-year treasury", "10-year yield", "ten-year yield", "treasury yield", "bond yield",
           "long-term rate", "10年期国债收益率", "美债收益率", "长期利率")),
    _fred("DGS30",
          "Market Yield on U.S. Treasury Securities at 30-Year Constant Maturity, Quoted on an Investment Basis",
          "美国30年期国债收益率", "Percent", "D", "NSA", ("rates",),
          ("30-year treasury", "long bond", "30-year yield", "30年期国债收益率")),
    _fred("T10Y2Y", "10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity",
          "美国10年期与2年期国债利差", "Percent", "D", "NSA", ("rates",),
          ("yield curve", "2s10s", "term spread", "inverted yield curve", "curve inversion",
           "收益率曲线", "期限利差", "倒挂")),
    _fred("T10Y3M", "10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity",
          "美国10年期与3个月期国债利差", "Percent", "D", "NSA", ("rates", "growth"),
          ("yield curve", "10y3m", "term spread", "curve inversion", "recession signal", "收益率曲线", "倒挂")),
    _fred("T10YIE", "10-Year Breakeven Inflation Rate", "美国10年期盈亏平衡通胀率", "Percent", "D", "NSA",
          ("inflation", "rates"),
          ("breakeven inflation", "inflation expectations", "market inflation expectations", "tips breakeven",
           "盈亏平衡通胀率", "通胀预期")),
    _fred("T5YIFR", "5-Year, 5-Year Forward Inflation Expectation Rate", "美国5年后5年远期通胀预期", "Percent",
          "D", "NSA", ("inflation", "rates"),
          ("5y5y", "forward inflation expectations", "long-run inflation expectations", "远期通胀预期")),
    _fred("DFII10",
          "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment "
          "Basis, Inflation-Indexed", "美国10年期通胀保值国债实际收益率", "Percent", "D", "NSA", ("rates",),
          ("real yield", "tips yield", "real interest rate", "实际收益率", "实际利率")),
    _fred("MORTGAGE30US", "30-Year Fixed Rate Mortgage Average in the United States", "美国30年期固定房贷平均利率",
          "Percent", "W", "NSA", ("rates", "housing"),
          ("mortgage rate", "30-year mortgage", "home loan rate", "房贷利率", "抵押贷款利率")),
    # Credit and markets
    _fred("BAMLH0A0HYM2", "ICE BofA US High Yield Index Option-Adjusted Spread", "美国高收益债期权调整利差",
          "Percent", "D", "NSA", ("credit", "markets"),
          ("high yield spread", "junk bond spread", "credit spread", "hy oas", "高收益债利差", "信用利差"),
          _ICE_NOTE),
    _fred("BAMLC0A0CM", "ICE BofA US Corporate Index Option-Adjusted Spread", "美国投资级公司债期权调整利差",
          "Percent", "D", "NSA", ("credit", "markets"),
          ("corporate bond spread", "investment grade spread", "credit spread", "ig oas", "公司债利差", "信用利差"),
          _ICE_NOTE),
    _fred("VIXCLS", "CBOE Volatility Index: VIX", "芝加哥期权交易所波动率指数VIX", "Index", "D", "NSA",
          ("markets",), ("vix", "volatility", "fear index", "market volatility", "波动率指数", "恐慌指数")),
    _fred("SP500", "S&P 500", "标普500指数", "Index", "D", "NSA", ("markets",),
          ("s&p 500", "stock market", "equities", "stocks", "us stocks", "标普500", "美股", "股市"),
          "FRED keeps only the latest ten years of daily values (licensing); price index without dividends."),
    # Dollar and FX (geography = the foreign economy for bilateral rates)
    _fred("DTWEXBGS", "Nominal Broad U.S. Dollar Index", "名义广义美元指数", "Index Jan 2006=100", "D", "NSA",
          ("fx",), ("dollar index", "broad dollar", "us dollar", "trade-weighted dollar", "dxy",
                    "美元指数", "美元汇率"),
          "Federal Reserve trade-weighted index (26 currencies), not the ICE DXY."),
    _fred("DEXUSEU", "U.S. Dollars to Euro Spot Exchange Rate", "欧元兑美元即期汇率", "U.S. Dollars to One Euro",
          "D", "NSA", ("fx",), ("euro exchange rate", "eur/usd", "eurusd", "euro dollar", "欧元汇率", "欧元兑美元"),
          _FX_NOTE, geography="EMU"),
    _fred("DEXJPUS", "Japanese Yen to U.S. Dollar Spot Exchange Rate", "美元兑日元即期汇率",
          "Japanese Yen to One U.S. Dollar", "D", "NSA", ("fx",),
          ("yen", "usd/jpy", "usdjpy", "yen exchange rate", "日元汇率", "日元"), _FX_NOTE, geography="JPN"),
    _fred("DEXCHUS", "Chinese Yuan Renminbi to U.S. Dollar Spot Exchange Rate", "美元兑人民币即期汇率",
          "Chinese Yuan Renminbi to One U.S. Dollar", "D", "NSA", ("fx",),
          ("yuan", "renminbi", "rmb", "cny", "usd/cny", "usdcny", "人民币汇率", "人民币"), _FX_NOTE,
          geography="CHN"),
    _fred("DEXUSUK", "U.S. Dollars to U.K. Pound Sterling Spot Exchange Rate", "英镑兑美元即期汇率",
          "U.S. Dollars to One U.K. Pound Sterling", "D", "NSA", ("fx",),
          ("pound", "sterling", "gbp/usd", "gbpusd", "cable", "英镑汇率"), _FX_NOTE, geography="GBR"),
    _fred("DEXMXUS", "Mexican Pesos to U.S. Dollar Spot Exchange Rate", "美元兑墨西哥比索即期汇率",
          "Mexican Pesos to One U.S. Dollar", "D", "NSA", ("fx",),
          ("peso", "mexican peso", "usd/mxn", "usdmxn", "比索汇率"), _FX_NOTE, geography="MEX"),
    _fred("DEXINUS", "Indian Rupees to U.S. Dollar Spot Exchange Rate", "美元兑印度卢比即期汇率",
          "Indian Rupees to One U.S. Dollar", "D", "NSA", ("fx",),
          ("rupee", "indian rupee", "usd/inr", "usdinr", "卢比汇率"), _FX_NOTE, geography="IND"),
    # Energy and commodities (global benchmarks carry geography WLD)
    _fred("DCOILWTICO", "Crude Oil Prices: West Texas Intermediate (WTI) - Cushing, Oklahoma", "WTI原油现货价格",
          "Dollars per Barrel", "D", "NSA", ("energy", "commodities"),
          ("wti", "oil price", "crude oil", "crude oil price", "oil", "原油价格", "油价", "wti原油"),
          "Daily spot price (EIA); weekends and holidays are missing.", geography="WLD"),
    _fred("DCOILBRENTEU", "Crude Oil Prices: Brent - Europe", "布伦特原油现货价格", "Dollars per Barrel", "D",
          "NSA", ("energy", "commodities"),
          ("brent", "brent crude", "oil price", "crude oil", "crude oil price", "布伦特原油", "油价", "原油价格"),
          "Daily spot price (EIA); weekends and holidays are missing.", geography="WLD"),
    _fred("DHHNGSP", "Henry Hub Natural Gas Spot Price", "美国亨利港天然气现货价格", "Dollars per Million BTU",
          "D", "NSA", ("energy", "commodities"),
          ("natural gas price", "henry hub", "us natural gas", "gas price", "天然气价格", "亨利港")),
    _fred("GASREGW", "US Regular All Formulations Gas Price", "美国普通汽油零售均价", "Dollars per Gallon", "W",
          "NSA", ("energy",),
          ("gasoline price", "gas price", "petrol price", "pump price", "汽油价格", "油价")),
    _fred("PNGASEUUSDM", "Global price of Natural gas, EU", "欧洲天然气价格（IMF）",
          "U.S. Dollars per Million Metric British Thermal Unit", "M", "NSA", ("energy", "commodities"),
          ("european gas price", "ttf", "eu natural gas", "europe gas", "欧洲天然气价格", "天然气价格"),
          "IMF primary commodity price (Netherlands TTF) mirrored on FRED; lags the IMF source by about "
          "two months (imf:PCPS/G001.PNGASEU.USD.M).", geography="EMU"),
    _fred("PCOPPUSDM", "Global price of Copper", "全球铜价（IMF）", "U.S. Dollars per Metric Ton", "M", "NSA",
          ("commodities",), ("copper price", "copper", "lme copper", "铜价", "铜"),
          "IMF primary commodity price mirrored on FRED; lags the IMF source (imf:PCPS/G001.PCOPP.USD.M).",
          geography="WLD"),
    # Trade and fiscal
    _fred("BOPGSTB", "Trade Balance: Goods and Services, Balance of Payments Basis", "美国商品和服务贸易差额",
          "Millions of Dollars", "M", "SA", ("trade",),
          ("trade balance", "trade deficit", "net exports", "贸易逆差", "贸易差额", "贸易平衡"),
          "Negative values are deficits."),
    _fred("EXPGSC1", "Real Exports of Goods and Services", "美国实际商品和服务出口",
          "Billions of Chained 2017 Dollars", "Q", "SAAR", ("trade",), ("real exports", "exports", "出口")),
    _fred("IMPGSC1", "Real imports of goods and services", "美国实际商品和服务进口",
          "Billions of Chained 2017 Dollars", "Q", "SAAR", ("trade",), ("real imports", "imports", "进口")),
    _fred("GFDEGDQ188S", "Federal Debt: Total Public Debt as Percent of Gross Domestic Product",
          "美国联邦公共债务占GDP比率", "Percent of GDP", "Q", "SA", ("fiscal",),
          ("debt to gdp", "federal debt", "public debt", "government debt", "national debt",
           "政府债务", "债务占gdp", "国债规模"),
          "Gross debt including intragovernmental holdings."),
    _fred("FYFSGDA188S", "Federal Surplus or Deficit [-] as Percent of Gross Domestic Product",
          "美国联邦财政盈余或赤字占GDP比率", "Percent of GDP", "A", "NSA", ("fiscal",),
          ("budget deficit", "fiscal deficit", "deficit to gdp", "财政赤字", "赤字率"),
          "Fiscal-year basis; negative values are deficits."),
)


# ---------------------------------------------------------------------------
# BLS (U.S. Bureau of Labor Statistics) -- titles and base periods from data.bls.gov
# ---------------------------------------------------------------------------

_CPI_UNITS = "Index 1982-84=100"
_PPI_LABEL_NOTE = ("Corrected label: the bundled bls-query catalog mislabels this id; the official BLS "
                   "title is shown here.")

_BLS_ENTRIES: tuple[CatalogEntry, ...] = (
    # Consumer prices
    _bls("CUUR0000SA0", "All items in U.S. city average, all urban consumers, not seasonally adjusted",
         "美国CPI-U全部项目（未季调）", _CPI_UNITS, "M", "NSA", ("inflation",),
         ("cpi", "headline cpi", "official inflation", "cpi-u", "inflation", "consumer prices",
          "消费者价格指数", "通胀", "cpi同比"),
         "Index level; the published 12-month inflation rate is the yoy change of this NSA series."),
    _bls("CUSR0000SA0", "All items in U.S. city average, all urban consumers, seasonally adjusted",
         "美国CPI-U全部项目（季调）", _CPI_UNITS, "M", "SA", ("inflation",),
         ("cpi", "monthly inflation", "cpi month over month", "cpi环比"),
         "Use for month-over-month changes; FRED mirror fred:CPIAUCSL."),
    _bls("CUUR0000SA0L1E",
         "All items less food and energy in U.S. city average, all urban consumers, not seasonally adjusted",
         "美国核心CPI（未季调）", _CPI_UNITS, "M", "NSA", ("inflation",),
         ("core cpi", "core inflation", "核心cpi", "核心通胀"),
         "The published 12-month core inflation rate is the yoy change of this NSA series."),
    _bls("CUSR0000SA0L1E",
         "All items less food and energy in U.S. city average, all urban consumers, seasonally adjusted",
         "美国核心CPI（季调）", _CPI_UNITS, "M", "SA", ("inflation",),
         ("core cpi", "core inflation", "核心cpi"), "FRED mirror fred:CPILFESL."),
    _bls("SUUR0000SA0", "All items in U.S. city average, all urban consumers, chained, not seasonally adjusted",
         "美国链式CPI-U", "Index Dec 1999=100", "M", "NSA", ("inflation",),
         ("chained cpi", "c-cpi-u", "链式cpi"),
         "Latest months are preliminary and revised for ten to twelve months."),
    _bls("CUSR0000SAH1", "Shelter in U.S. city average, all urban consumers, seasonally adjusted",
         "美国CPI住房分项", _CPI_UNITS, "M", "SA", ("inflation", "housing"),
         ("shelter inflation", "shelter cpi", "housing inflation", "住房通胀", "住房成本")),
    _bls("CUSR0000SEHA", "Rent of primary residence in U.S. city average, all urban consumers, seasonally adjusted",
         "美国CPI主要住所租金", _CPI_UNITS, "M", "SA", ("inflation", "housing"),
         ("rent inflation", "rents", "rent cpi", "租金", "房租")),
    _bls("CUSR0000SAF11", "Food at home in U.S. city average, all urban consumers, seasonally adjusted",
         "美国CPI家庭食品", _CPI_UNITS, "M", "SA", ("inflation",),
         ("food inflation", "grocery prices", "food at home", "食品通胀", "食品价格")),
    _bls("CUSR0000SAM", "Medical care in U.S. city average, all urban consumers, seasonally adjusted",
         "美国CPI医疗保健", _CPI_UNITS, "M", "SA", ("inflation",),
         ("medical care inflation", "health care prices", "医疗通胀", "医疗价格")),
    _bls("CUSR0000SETA02", "Used cars and trucks in U.S. city average, all urban consumers, seasonally adjusted",
         "美国CPI二手车", _CPI_UNITS, "M", "SA", ("inflation",),
         ("used car prices", "used cars", "二手车价格")),
    _bls("CUSR0000SASLE",
         "Services less energy services in U.S. city average, all urban consumers, seasonally adjusted",
         "美国CPI核心服务（剔除能源服务）", _CPI_UNITS, "M", "SA", ("inflation",),
         ("services inflation", "core services", "服务通胀", "核心服务")),
    _bls("CUUR0000SETB01", "Gasoline (all types) in U.S. city average, all urban consumers, not seasonally adjusted",
         "美国CPI汽油", _CPI_UNITS, "M", "NSA", ("inflation", "energy"),
         ("gasoline cpi", "gasoline inflation", "汽油价格指数")),
    _bls("CUUR0000SEHF01", "Electricity in U.S. city average, all urban consumers, not seasonally adjusted",
         "美国CPI电力", _CPI_UNITS, "M", "NSA", ("inflation", "energy"),
         ("electricity prices", "electricity cpi", "power prices", "电价", "电力价格")),
    # Average prices
    _bls("APU000074714",
         "Gasoline, unleaded regular, per gallon/3.785 liters in U.S. city average, average price, "
         "not seasonally adjusted", "美国普通无铅汽油平均价格", "U.S. dollars per gallon", "M", "NSA",
         ("energy", "inflation"), ("gasoline price", "gas price", "average gasoline price", "汽油价格", "油价"),
         "Monthly average price; weekly retail prices are fred:GASREGW."),
    _bls("APU000072610", "Electricity per KWH in U.S. city average, average price, not seasonally adjusted",
         "美国居民电价（每千瓦时平均价格）", "U.S. dollars per kilowatt-hour", "M", "NSA", ("energy", "inflation"),
         ("electricity price", "price per kwh", "residential electricity price", "电价", "居民电价")),
    _bls("APU0000708111", "Eggs, grade A, large, per doz. in U.S. city average, average price, not seasonally adjusted",
         "美国A级大鸡蛋平均价格", "U.S. dollars per dozen", "M", "NSA", ("inflation",),
         ("egg prices", "eggs", "鸡蛋价格")),
    _bls("APU0000703112",
         "Ground beef, 100% beef, per lb. (453.6 gm) in U.S. city average, average price, not seasonally adjusted",
         "美国碎牛肉平均价格", "U.S. dollars per pound", "M", "NSA", ("inflation",),
         ("beef prices", "ground beef", "meat prices", "牛肉价格")),
    # Producer prices (labels corrected against data.bls.gov)
    _bls("WPSFD4", "PPI Commodity data for Final demand, seasonally adjusted", "美国PPI最终需求（季调）",
         "Index Nov 2009=100", "M", "SA", ("inflation",),
         ("ppi", "producer prices", "producer price index", "final demand", "生产者价格指数", "ppi环比"),
         _PPI_LABEL_NOTE + " Not 'Finished Goods'."),
    _bls("WPUFD4", "PPI Commodity data for Final demand, not seasonally adjusted", "美国PPI最终需求（未季调）",
         "Index Nov 2009=100", "M", "NSA", ("inflation",),
         ("ppi", "producer prices", "headline ppi", "生产者价格指数", "ppi同比"),
         "The published 12-month PPI change is the yoy change of this NSA series."),
    _bls("WPUFD49104", "PPI Commodity data for Final demand less foods and energy, not seasonally adjusted",
         "美国核心PPI（剔除食品和能源）", "Index Apr 2010=100", "M", "NSA", ("inflation",),
         ("core ppi", "ppi less food and energy", "核心ppi"),
         _PPI_LABEL_NOTE + " The catalog's WPSFD49104 'Finished Goods Less Food and Energy' is a different series."),
    _bls("WPUFD49116",
         "PPI Commodity data for Final demand less foods, energy, and trade services, not seasonally adjusted",
         "美国PPI最终需求（剔除食品、能源和贸易服务）", "Index Aug 2013=100", "M", "NSA", ("inflation",),
         ("supercore ppi", "ppi less food energy and trade", "超级核心ppi"),
         _PPI_LABEL_NOTE + " Not 'PPI: Final Demand' (that is WPUFD4)."),
    _bls("WPU0561",
         "PPI Commodity data for Fuels and related products and power-Crude petroleum (domestic production), "
         "not seasonally adjusted", "美国PPI国产原油", "Index 1982=100", "M", "NSA", ("energy", "inflation"),
         ("crude oil ppi", "crude petroleum prices", "原油ppi")),
    _bls("PCU221110221110", "PPI industry data for Electric power generation, not seasonally adjusted",
         "美国PPI发电行业", "Index Dec 2003=100", "M", "NSA", ("energy", "inflation"),
         ("electric power generation prices", "wholesale power prices", "发电价格")),
    # Labor market
    _bls("LNS14000000", "(Seas) Unemployment Rate", "美国失业率（16岁及以上，季调）", "Percent", "M", "SA",
         ("labor",), ("unemployment rate", "unemployment", "jobless rate", "失业率"),
         "Household survey (CPS); FRED mirror fred:UNRATE. October 2025 missing (2025 federal shutdown)."),
    _bls("LNU04000000", "(Unadj) Unemployment Rate", "美国失业率（未季调）", "Percent", "M", "NSA", ("labor",),
         ("unadjusted unemployment rate", "nsa unemployment", "未季调失业率")),
    _bls("LNS11300000", "(Seas) Labor Force Participation Rate", "美国劳动参与率", "Percent", "M", "SA", ("labor",),
         ("participation rate", "labor force participation", "劳动参与率")),
    _bls("LNS12300060", "(Seas) Employment-Population Ratio - 25-54 yrs.", "美国25-54岁就业人口比", "Percent", "M",
         "SA", ("labor",), ("prime-age employment", "employment-population ratio", "epop", "核心年龄段就业率")),
    _bls("CES0000000001", "All employees, thousands, total nonfarm, seasonally adjusted", "美国非农就业人数",
         "Thousands of persons", "M", "SA", ("labor",),
         ("nonfarm payrolls", "payrolls", "jobs report", "非农就业", "非农"),
         "Establishment survey; FRED mirror fred:PAYEMS. Latest two months are preliminary."),
    _bls("CES3000000001", "All employees, thousands, manufacturing, seasonally adjusted", "美国制造业就业人数",
         "Thousands of persons", "M", "SA", ("labor", "production"),
         ("manufacturing jobs", "manufacturing employment", "factory jobs", "制造业就业")),
    _bls("CES0500000003", "Average hourly earnings of all employees, total private, seasonally adjusted",
         "美国私营部门平均时薪", "U.S. dollars per hour", "M", "SA", ("labor", "income"),
         ("average hourly earnings", "wage growth", "wages", "平均时薪", "工资增长")),
    _bls("CES0500000011", "Average weekly earnings of all employees, total private, seasonally adjusted",
         "美国私营部门平均周薪", "U.S. dollars per week", "M", "SA", ("labor", "income"),
         ("average weekly earnings", "weekly pay", "平均周薪")),
    _bls("CES0500000002", "Average weekly hours of all employees, total private, seasonally adjusted",
         "美国私营部门平均每周工时", "Hours", "M", "SA", ("labor",),
         ("average weekly hours", "hours worked", "workweek", "平均工时")),
    _bls("JTS000000000000000JOL", "Job openings: total nonfarm, all size classes, level in thousands, seasonally adjusted",
         "美国职位空缺数（JOLTS）", "Thousands", "M", "SA", ("labor",),
         ("job openings", "jolts", "vacancies", "职位空缺"),
         "Published about five weeks after the reference month; FRED mirror fred:JTSJOL."),
    _bls("JTS000000000000000QUR", "Quits rate: total nonfarm, all size classes, seasonally adjusted",
         "美国离职率（主动辞职）", "Percent", "M", "SA", ("labor",),
         ("quits rate", "quit rate", "job switching", "辞职率", "离职率")),
    _bls("JTS000000000000000HIR", "Hires rate: total nonfarm, all size classes, seasonally adjusted",
         "美国招聘率", "Percent", "M", "SA", ("labor",), ("hires rate", "hiring rate", "招聘率")),
    _bls("JTS000000000000000LDR", "Layoffs and discharges rate: total nonfarm, all size classes, seasonally adjusted",
         "美国裁员率", "Percent", "M", "SA", ("labor",), ("layoffs rate", "layoffs", "discharges", "裁员率")),
    _bls("LASST060000000000003", "Unemployment rate: California, statewide, seasonally adjusted",
         "加州失业率", "Percent", "M", "SA", ("labor",),
         ("california unemployment", "state unemployment", "加州失业率"), "LAUS state estimate; revised annually."),
    _bls("LASST480000000000003", "Unemployment rate: Texas, statewide, seasonally adjusted",
         "得克萨斯州失业率", "Percent", "M", "SA", ("labor",),
         ("texas unemployment", "state unemployment", "德州失业率"), "LAUS state estimate; revised annually."),
    _bls("LASST360000000000003", "Unemployment rate: New York, statewide, seasonally adjusted",
         "纽约州失业率", "Percent", "M", "SA", ("labor",),
         ("new york unemployment", "state unemployment", "纽约州失业率"), "LAUS state estimate; revised annually."),
    # Compensation, productivity, trade prices
    _bls("CIU1010000000000A", "Total compensation for all civilian workers, 12-month percent change, current dollars",
         "美国雇佣成本指数（总薪酬，同比）", "Percent change over 12 months", "Q", "NSA", ("labor", "income"),
         ("employment cost index", "eci", "labor costs", "compensation growth", "雇佣成本指数"),
         "Id suffix encodes the measure: A = 12-month percent change, I = index, Q = 3-month percent change."),
    _bls("CIU1010000000000I", "Total compensation for all civilian workers, current dollar index",
         "美国雇佣成本指数（总薪酬，指数）", "Index Dec 2005=100", "Q", "NSA", ("labor", "income"),
         ("employment cost index level", "eci index", "雇佣成本指数")),
    _bls("PRS85006092", "Nonfarm Business: Labor productivity (output per hour), % change from previous quarter",
         "美国非农企业劳动生产率（环比折年率）", "Percent change from previous quarter at annual rate", "Q", "SA",
         ("labor", "growth"), ("productivity", "labor productivity", "output per hour", "劳动生产率")),
    _bls("PRS85006112", "Nonfarm Business: Unit labor costs, % change from previous quarter",
         "美国非农企业单位劳动力成本（环比折年率）", "Percent change from previous quarter at annual rate", "Q", "SA",
         ("labor", "inflation"), ("unit labor costs", "labor costs", "单位劳动力成本")),
    _bls("EIUIR", "Monthly import price index for BEA End Use, All commodities, not seasonally adjusted",
         "美国进口价格指数", "Index 2000=100", "M", "NSA", ("trade", "inflation"),
         ("import prices", "import price index", "tariff pass-through", "进口价格")),
    _bls("EIUIQ", "Monthly export price index for BEA End Use, All commodities, not seasonally adjusted",
         "美国出口价格指数", "Index 2000=100", "M", "NSA", ("trade", "inflation"),
         ("export prices", "export price index", "出口价格")),
)


# ---------------------------------------------------------------------------
# BIS (Bank for International Settlements) -- titles from the series TITLE / TITLE_TS
# ---------------------------------------------------------------------------

# BIS REF_AREA -> (ISO3, BIS area name, Chinese name, policy-rate keywords)
_BIS_AREAS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "US": ("USA", "United States", "美国", ("federal reserve", "fed", "fomc", "美联储")),
    "XM": ("EMU", "Euro area", "欧元区", ("ecb", "european central bank", "deposit facility rate", "欧洲央行")),
    "GB": ("GBR", "United Kingdom", "英国", ("bank of england", "boe", "bank rate", "英国央行", "英格兰银行")),
    "JP": ("JPN", "Japan", "日本", ("bank of japan", "boj", "日本央行")),
    "CN": ("CHN", "China", "中国", ("people's bank of china", "pboc", "中国人民银行", "人民银行")),
    "IN": ("IND", "India", "印度", ("reserve bank of india", "rbi", "repo rate", "印度央行")),
    "BR": ("BRA", "Brazil", "巴西", ("banco central do brasil", "selic", "巴西央行")),
    "CA": ("CAN", "Canada", "加拿大", ("bank of canada", "加拿大央行")),
    "KR": ("KOR", "Korea", "韩国", ("bank of korea", "韩国央行")),
    "AU": ("AUS", "Australia", "澳大利亚", ("reserve bank of australia", "rba", "cash rate", "澳洲联储")),
    "CH": ("CHE", "Switzerland", "瑞士", ("swiss national bank", "snb", "瑞士央行")),
    "MX": ("MEX", "Mexico", "墨西哥", ("banco de mexico", "banxico", "墨西哥央行")),
}


def _cbpol(area: str) -> CatalogEntry:
    iso3, name, name_zh, extra = _BIS_AREAS[area]
    notes = ("For the United States BIS reports the midpoint of the federal funds target range; "
             "fred:DFEDTARU is the upper limit." if area == "US" else "")
    return _bis("WS_CBPOL", f"M.{area}", f"Central bank policy rates - {name} - Monthly - End of period",
                f"{name_zh}央行政策利率", "Per cent per year", iso3, ("rates", "policy"),
                ("policy rate", "central bank rate", "interest rate", "benchmark rate", "rate cut", "rate hike",
                 "政策利率", "央行利率", "基准利率", "降息", "加息") + extra, notes)


def _credit_gap(area: str) -> CatalogEntry:
    iso3, name, name_zh, _extra = _BIS_AREAS[area]
    return _bis("WS_CREDIT_GAP", f"Q.{area}.P.A.C",
                f"Credit-to-GDP gaps (actual-trend): {name} - Private non-financial sector",
                f"{name_zh}信贷/GDP缺口", "Percentage points of GDP", iso3, ("credit",),
                ("credit gap", "credit-to-gdp gap", "credit boom", "banking crisis risk", "countercyclical buffer",
                 "信贷缺口", "信贷gdp缺口", "杠杆"),
                "Above 10 percentage points is the Basel early-warning zone; one-sided HP trend.")


_BIS_ENTRIES: tuple[CatalogEntry, ...] = (
    tuple(_cbpol(area) for area in ("US", "XM", "GB", "JP", "CN", "IN", "BR", "CA", "KR", "AU", "CH", "MX"))
    + tuple(_credit_gap(area) for area in ("US", "XM", "GB", "JP", "CN"))
    + (
        _bis("WS_TC", "Q.US.P.A.M.770.A",
             "United States - Credit to Private non-financial sector from All sectors at Market value - "
             "Percentage of GDP - Adjusted for breaks", "美国私人非金融部门信贷占GDP比率", "Percentage of GDP",
             "USA", ("credit",), ("private credit", "private debt", "credit to gdp", "leverage", "私人部门杠杆率",
                                  "信贷占gdp")),
        _bis("WS_TC", "Q.US.H.A.M.770.A",
             "United States - Credit to Households and NPISHs from All sectors at Market value - "
             "Percentage of GDP - Adjusted for breaks", "美国居民部门信贷占GDP比率", "Percentage of GDP", "USA",
             ("credit", "housing"), ("household debt", "household leverage", "居民杠杆率", "家庭债务")),
        _bis("WS_TC", "Q.US.G.A.M.770.A",
             "United States - Credit to General government from All sectors at Market value - "
             "Percentage of GDP - Adjusted for breaks", "美国政府部门信贷占GDP比率", "Percentage of GDP", "USA",
             ("credit", "fiscal"), ("government debt", "public debt", "政府杠杆率", "政府债务"),
             "Market value of government debt; differs from the face-value debt-to-GDP ratio."),
        _bis("WS_TC", "Q.CN.P.A.M.770.A",
             "China - Credit to Private non-financial sector from All sectors at Market value - "
             "Percentage of GDP - Adjusted for breaks", "中国私人非金融部门信贷占GDP比率", "Percentage of GDP",
             "CHN", ("credit",), ("private credit", "private debt", "corporate debt", "leverage", "credit to gdp",
                                  "私人部门杠杆率", "企业杠杆率", "信贷占gdp")),
        _bis("WS_TC", "Q.CN.H.A.M.770.A",
             "China - Credit to Households and NPISHs from All sectors at Market value - "
             "Percentage of GDP - Adjusted for breaks", "中国居民部门信贷占GDP比率", "Percentage of GDP", "CHN",
             ("credit", "housing"), ("household debt", "household leverage", "居民杠杆率", "家庭债务")),
        _bis("WS_TC", "Q.JP.G.A.M.770.A",
             "Japan - Credit to General government from All sectors at Market value - "
             "Percentage of GDP - Adjusted for breaks", "日本政府部门信贷占GDP比率", "Percentage of GDP", "JPN",
             ("credit", "fiscal"), ("government debt", "public debt", "政府债务", "政府杠杆率")),
        _bis("WS_DSR", "Q.US.P", "Debt service ratios: United States - Private non-financial sector",
             "美国私人非金融部门偿债比率", "Per cent of income", "USA", ("credit",),
             ("debt service ratio", "debt burden", "interest burden", "偿债比率", "偿债负担")),
        _bis("WS_DSR", "Q.US.H", "Debt service ratios: United States - Households and NPISHs",
             "美国居民部门偿债比率", "Per cent of income", "USA", ("credit", "income"),
             ("household debt service", "household debt burden", "居民偿债比率")),
        _bis("WS_DSR", "Q.CN.P", "Debt service ratios: China - Private non-financial sector",
             "中国私人非金融部门偿债比率", "Per cent of income", "CHN", ("credit",),
             ("debt service ratio", "debt burden", "偿债比率", "偿债负担")),
        _bis("WS_DSR", "Q.GB.P", "Debt service ratios: United Kingdom - Private non-financial sector",
             "英国私人非金融部门偿债比率", "Per cent of income", "GBR", ("credit",),
             ("debt service ratio", "debt burden", "偿债比率")),
        _bis("WS_SPP", "Q.US.R.628", "Residential property prices: United States - Real - Index, 2010 = 100",
             "美国实际住宅价格指数", "Index, 2010 = 100", "USA", ("housing",),
             ("real house prices", "real home prices", "property prices", "实际房价", "房价")),
        _bis("WS_SPP", "Q.US.N.628", "Residential property prices: United States - Nominal - Index, 2010 = 100",
             "美国名义住宅价格指数", "Index, 2010 = 100", "USA", ("housing",),
             ("nominal house prices", "home prices", "property prices", "名义房价", "房价")),
        _bis("WS_SPP", "Q.CN.R.628", "Residential property prices: China - Real - Index, 2010 = 100",
             "中国实际住宅价格指数", "Index, 2010 = 100", "CHN", ("housing",),
             ("china house prices", "china property prices", "property market", "real estate prices",
              "中国房价", "房价", "楼市", "房地产价格")),
        _bis("WS_SPP", "Q.GB.R.628", "Residential property prices: United Kingdom - Real - Index, 2010 = 100",
             "英国实际住宅价格指数", "Index, 2010 = 100", "GBR", ("housing",),
             ("uk house prices", "property prices", "英国房价", "房价")),
        _bis("WS_XRU", "M.JP.JPY.A",
             "Exchange rates against USD Japan - Yen - Monthly - Average of observations through period",
             "日元兑美元汇率（月均）", "Yen per US dollar", "JPN", ("fx",),
             ("yen", "usd/jpy", "yen exchange rate", "日元汇率")),
        _bis("WS_XRU", "M.CN.CNY.A",
             "Exchange rates against USD China - Renminbi - Monthly - Average of observations through period",
             "人民币兑美元汇率（月均）", "Renminbi per US dollar", "CHN", ("fx",),
             ("renminbi", "yuan", "cny", "usd/cny", "人民币汇率")),
        _bis("WS_XRU", "M.XM.EUR.A",
             "Exchange rates against USD Euro area - Euro - Monthly - Average of observations through period",
             "欧元兑美元汇率（月均）", "Euro per US dollar", "EMU", ("fx",),
             ("euro exchange rate", "eur/usd", "欧元汇率"),
             "Quoted as euros per US dollar (the inverse of the usual EUR/USD quote)."),
        _bis("WS_XRU", "M.GB.GBP.A",
             "Exchange rates against USD United Kingdom - Pound (sterling) - Monthly - Average of observations "
             "through period", "英镑兑美元汇率（月均）", "Pounds sterling per US dollar", "GBR", ("fx",),
             ("pound", "sterling", "gbp/usd", "英镑汇率"),
             "Quoted as pounds per US dollar (the inverse of the usual GBP/USD quote)."),
        _bis("WS_XRU", "M.IN.INR.A",
             "Exchange rates against USD India - Indian rupee - Monthly - Average of observations through period",
             "印度卢比兑美元汇率（月均）", "Indian rupees per US dollar", "IND", ("fx",),
             ("rupee", "usd/inr", "卢比汇率")),
        _bis("WS_EER", "M.R.B.US", "Effective exchange rates: United States - Real - Broad (64 economies)",
             "美元实际有效汇率", "Index, 2020 = 100", "USA", ("fx", "trade"),
             ("real effective exchange rate", "reer", "dollar strength", "实际有效汇率", "美元汇率")),
        _bis("WS_EER", "M.N.B.US", "Effective exchange rates: United States - Nominal - Broad (64 economies)",
             "美元名义有效汇率", "Index, 2020 = 100", "USA", ("fx", "trade"),
             ("nominal effective exchange rate", "neer", "trade-weighted dollar", "名义有效汇率")),
        _bis("WS_EER", "M.R.B.CN", "Effective exchange rates: China - Real - Broad (64 economies)",
             "人民币实际有效汇率", "Index, 2020 = 100", "CHN", ("fx", "trade"),
             ("real effective exchange rate", "reer", "renminbi", "人民币实际有效汇率")),
        _bis("WS_EER", "M.R.B.XM", "Effective exchange rates: Euro area - Real - Broad (64 economies)",
             "欧元实际有效汇率", "Index, 2020 = 100", "EMU", ("fx", "trade"),
             ("real effective exchange rate", "reer", "euro", "欧元实际有效汇率")),
        _bis("WS_EER", "M.R.B.JP", "Effective exchange rates: Japan - Real - Broad (64 economies)",
             "日元实际有效汇率", "Index, 2020 = 100", "JPN", ("fx", "trade"),
             ("real effective exchange rate", "reer", "yen", "日元实际有效汇率")),
        _bis("WS_LONG_CPI", "M.US.771", "Consumer prices: United States - Year-on-year changes, in per cent",
             "美国CPI同比（BIS）", "Per cent, year-on-year change", "USA", ("inflation",),
             ("inflation", "cpi", "consumer prices", "通胀", "cpi同比")),
        _bis("WS_LONG_CPI", "M.CN.771", "Consumer prices: China - Year-on-year changes, in per cent",
             "中国CPI同比（BIS）", "Per cent, year-on-year change", "CHN", ("inflation",),
             ("inflation", "cpi", "consumer prices", "deflation", "通胀", "通缩", "cpi同比")),
        _bis("WS_LONG_CPI", "M.XM.771", "Consumer prices: Euro area - Year-on-year changes, in per cent",
             "欧元区CPI同比（BIS）", "Per cent, year-on-year change", "EMU", ("inflation",),
             ("inflation", "hicp", "consumer prices", "通胀"), "Euro-area HICP as compiled by the BIS."),
        _bis("WS_LONG_CPI", "M.JP.771", "Consumer prices: Japan - Year-on-year changes, in per cent",
             "日本CPI同比（BIS）", "Per cent, year-on-year change", "JPN", ("inflation",),
             ("inflation", "cpi", "consumer prices", "通胀")),
        _bis("WS_CBTA", "M.US.B.XDC.USD.N", "United States - Central bank, assets, total, BIS-spliced",
             "美联储总资产（BIS）", "US dollar, billions", "USA", ("money", "policy"),
             ("central bank balance sheet", "fed balance sheet", "quantitative tightening", "央行资产负债表", "缩表")),
        _bis("WS_CBTA", "M.XM.B.XDC.EUR.N", "Euro area - Central bank, assets, total, BIS-spliced",
             "欧元体系总资产", "Euro, billions", "EMU", ("money", "policy"),
             ("central bank balance sheet", "ecb balance sheet", "eurosystem assets", "欧洲央行资产负债表")),
        _bis("WS_CBTA", "M.JP.B.XDC.JPY.N", "Japan - Central bank, assets, total, BIS-spliced",
             "日本央行总资产", "Japanese yen, billions", "JPN", ("money", "policy"),
             ("central bank balance sheet", "boj balance sheet", "日本央行资产负债表")),
        _bis("WS_CBTA", "M.CN.B.XDC.CNY.N", "China - Central bank, assets, total, BIS-spliced",
             "中国人民银行总资产", "Chinese yuan renminbi, billions", "CHN", ("money", "policy"),
             ("central bank balance sheet", "pboc balance sheet", "央行资产负债表")),
        _bis("WS_GLI", "Q.USD.3P.N.A.I.B.USD",
             "USD denominated credit (bank loans & debt securities) to non-bank borrowers located outside the US",
             "美国境外非银行借款人的美元信贷", "US dollar, millions", "WLD", ("credit", "money", "fx"),
             ("global dollar liquidity", "dollar credit", "offshore dollar", "global liquidity", "全球美元流动性",
              "离岸美元")),
    )
)


# ---------------------------------------------------------------------------
# IMF (WEO aggregates and vintages, PCPS commodity prices, CPI)
# ---------------------------------------------------------------------------

_PCPS_NOTE = "IMF Primary Commodity Prices, monthly average of daily quotes."
_WEO_NOTE = ("IMF World Economic Outlook: values after the latest completed year are IMF projections "
             "(horizon about five years).")
_VINTAGE_NOTE = ("Frozen WEO vintage: compare with the live imf:WEO series to see how the IMF forecast "
                 "was revised. No data.imf.org page per vintage; the WEO dataset page is cited.")


def _pcps(code: str, title: str, title_zh: str, units: str, topics: tuple[str, ...],
          keywords: tuple[str, ...], notes: str = _PCPS_NOTE, transformation: str = "USD") -> CatalogEntry:
    return _imf("PCPS", f"G001.{code}.{transformation}.M", title, title_zh, units, "WLD", topics, keywords, notes)


def _imf_cpi(iso3: str, name: str, name_zh: str, extra: tuple[str, ...] = ()) -> CatalogEntry:
    return _imf("CPI", f"{iso3}.CPI._T.YOY_PCH_PA_PT.M",
                f"Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: {name}",
                f"{name_zh}CPI同比（IMF）", "Percent change, year over year", iso3, ("inflation",),
                ("inflation", "cpi", "consumer prices", "通胀", "cpi同比") + extra,
                "IMF CPI dataset; the latest month lags national releases by one to two months.")


_IMF_ENTRIES: tuple[CatalogEntry, ...] = (
    # WEO aggregates (Data360 carries WEO countries only)
    _imf("WEO", "G001.NGDP_RPCH.A", "Gross domestic product (GDP), Constant prices, Percent change: World",
         "世界实际GDP增长率（IMF WEO）", "Percent change", "WLD", ("growth", "projections"),
         ("world gdp growth", "global growth", "global gdp", "world economy", "全球经济增长", "世界经济增长",
          "全球gdp增长"), _WEO_NOTE),
    _imf("WEO", "G163.NGDP_RPCH.A", "Gross domestic product (GDP), Constant prices, Percent change: Euro Area (EA)",
         "欧元区实际GDP增长率（IMF WEO）", "Percent change", "EMU", ("growth", "projections"),
         ("euro area gdp growth", "eurozone growth", "gdp growth", "economic growth", "欧元区经济增长", "gdp增长"),
         _WEO_NOTE),
    _imf("WEO", "USA.NGDP_RPCH.A", "Gross domestic product (GDP), Constant prices, Percent change: United States",
         "美国实际GDP增长率（IMF WEO）", "Percent change", "USA", ("growth", "projections"),
         ("gdp growth", "imf forecast", "economic growth", "gdp增长", "imf预测"),
         _WEO_NOTE + " Same values as wb:IMF_WEO_NGDP_RPCH/USA, which is faster."),
    _imf("WEO", "G001.PCPIPCH.A",
         "All Items, Consumer price index (CPI), Period average, percent change: World",
         "世界CPI通胀率（IMF WEO）", "Percent change", "WLD", ("inflation", "projections"),
         ("global inflation", "world inflation", "全球通胀"), _WEO_NOTE),
    _imf("WEO", "G163.PCPIPCH.A",
         "All Items, Consumer price index (CPI), Period average, percent change: Euro Area (EA)",
         "欧元区CPI通胀率（IMF WEO）", "Percent change", "EMU", ("inflation", "projections"),
         ("euro area inflation", "eurozone inflation", "inflation", "欧元区通胀", "通胀"), _WEO_NOTE),
    _imf("WEO", "G163.LUR.A", "Unemployment rate: Euro Area (EA)", "欧元区失业率（IMF WEO）",
         "Percent of labor force", "EMU", ("labor", "projections"),
         ("euro area unemployment", "eurozone unemployment", "unemployment rate", "欧元区失业率", "失业率"), _WEO_NOTE),
    _imf("WEO", "G001.NGDPD.A", "Gross domestic product (GDP), Current prices, US dollar: World",
         "世界名义GDP（美元，IMF WEO）", "U.S. dollars", "WLD", ("growth", "projections"),
         ("world gdp", "global gdp size", "world economy size", "全球gdp规模", "世界经济总量"),
         _WEO_NOTE + " Values are whole U.S. dollars (IMF SCALE 9 is a display hint); divide by 1e12 for trillions."),
    _imf("WEO", "G001.POILBRE.A", "Brent crude, Unit prices, US dollars per barrel: World (WEO assumption)",
         "布伦特油价假设（IMF WEO）", "U.S. dollars per barrel", "WLD", ("energy", "commodities", "projections"),
         ("oil price forecast", "oil price assumption", "brent forecast", "油价预测", "油价假设"),
         "WEO baseline oil-price assumption (futures-based), not an IMF price forecast in the usual sense."),
    _imf("WEO", "G001.TRADEPCH.A", "Trade of goods and services, Volume, Percent change: World",
         "世界贸易量增长率（IMF WEO）", "Percent change", "WLD", ("trade", "projections"),
         ("world trade growth", "global trade volume", "trade volume", "全球贸易增长", "世界贸易量"), _WEO_NOTE),
    # WEO vintages (forecast revisions)
    _imf("WEO_2026_APR_VINTAGE", "USA.NGDP_RPCH.A",
         "Gross domestic product (GDP), Constant prices, Percent change: United States (WEO April 2026 vintage)",
         "美国GDP增长率（IMF WEO 2026年4月版）", "Percent change", "USA", ("growth", "projections"),
         ("imf forecast revision", "weo vintage", "april 2026 weo", "imf预测修订"), _VINTAGE_NOTE),
    _imf("WEO_2026_APR_VINTAGE", "CHN.NGDP_RPCH.A",
         "Gross domestic product (GDP), Constant prices, Percent change: China (WEO April 2026 vintage)",
         "中国GDP增长率（IMF WEO 2026年4月版）", "Percent change", "CHN", ("growth", "projections"),
         ("imf forecast revision", "weo vintage", "april 2026 weo", "imf预测修订"), _VINTAGE_NOTE),
    _imf("WEO_2025_OCT_VINTAGE", "USA.NGDP_RPCH.A",
         "Gross domestic product (GDP), Constant prices, Percent change: United States (WEO October 2025 vintage)",
         "美国GDP增长率（IMF WEO 2025年10月版）", "Percent change", "USA", ("growth", "projections"),
         ("imf forecast revision", "weo vintage", "october 2025 weo", "imf预测修订"), _VINTAGE_NOTE),
    _imf("WEO_2025_OCT_VINTAGE", "CHN.NGDP_RPCH.A",
         "Gross domestic product (GDP), Constant prices, Percent change: China (WEO October 2025 vintage)",
         "中国GDP增长率（IMF WEO 2025年10月版）", "Percent change", "CHN", ("growth", "projections"),
         ("imf forecast revision", "weo vintage", "october 2025 weo", "imf预测修订"), _VINTAGE_NOTE),
    # Primary commodity prices
    _pcps("POILBRE", "Brent Crude, US dollars per barrel, Unit prices", "布伦特原油价格（IMF月均）",
          "U.S. dollars per barrel", ("energy", "commodities"),
          ("brent", "oil price", "crude oil price", "布伦特原油", "油价")),
    _pcps("POILWTI", "WTI Crude, US dollars per barrel, Unit prices", "WTI原油价格（IMF月均）",
          "U.S. dollars per barrel", ("energy", "commodities"), ("wti", "oil price", "crude oil price", "wti原油", "油价")),
    _pcps("PNGASEU", "Natural gas, EU, US dollars per million metric British thermal units of gas, Unit prices",
          "欧洲天然气价格（TTF，IMF月均）", "U.S. dollars per million British thermal units", ("energy", "commodities"),
          ("european gas price", "ttf", "eu natural gas", "欧洲天然气价格", "天然气价格"),
          _PCPS_NOTE + " Netherlands TTF day-ahead."),
    _pcps("PNGASJP", "LNG, Asia, US dollars per million metric British thermal units of gas, Unit prices",
          "亚洲液化天然气价格（IMF月均）", "U.S. dollars per million British thermal units", ("energy", "commodities"),
          ("lng price", "asian lng", "liquefied natural gas", "液化天然气价格", "lng")),
    _pcps("PCOALAU", "Coal, Australia, US dollars per metric tonne, Unit prices", "澳大利亚动力煤价格（IMF月均）",
          "U.S. dollars per metric ton", ("energy", "commodities"),
          ("coal price", "thermal coal", "newcastle coal", "煤价", "动力煤")),
    _pcps("PURAN", "Uranium, US dollars per pound, Unit prices", "铀价格（IMF月均）", "U.S. dollars per pound",
          ("energy", "commodities"), ("uranium price", "uranium", "nuclear fuel", "铀价")),
    _pcps("PCOPP", "Copper, US dollars per metric tonne, Unit prices", "铜价格（IMF月均）", "U.S. dollars per metric ton",
          ("commodities",), ("copper price", "copper", "lme copper", "铜价", "铜")),
    _pcps("PALUM", "Aluminum, US dollars per metric tonne, Unit prices", "铝价格（IMF月均）", "U.S. dollars per metric ton",
          ("commodities",), ("aluminum price", "aluminium", "aluminum", "铝价")),
    _pcps("PNICK", "Nickel, US dollars per metric tonne, Unit prices", "镍价格（IMF月均）", "U.S. dollars per metric ton",
          ("commodities",), ("nickel price", "nickel", "battery metals", "镍价")),
    _pcps("PCOBA", "Cobalt, US dollars per pound, Unit prices", "钴价格（IMF月均）", "U.S. dollars per metric ton",
          ("commodities",), ("cobalt price", "cobalt", "battery metals", "钴价"),
          "IMF label says per pound, but the series description (LME spot, USD/ton) and the magnitude are "
          "US dollars per metric ton."),
    _pcps("PLITH", "Lithium, 99%, Battery Grade, Unit prices", "锂价格（电池级，IMF月均）",
          "U.S. dollars (IMF states no unit)", ("commodities", "energy"),
          ("lithium price", "lithium", "battery metals", "ev batteries", "锂价", "碳酸锂", "电池金属"),
          "Lithium metal 99% battery grade; IMF publishes no unit (magnitude consistent with US dollars per "
          "metric ton). Not lithium carbonate: compare changes, not levels, with carbonate quotes."),
    _pcps("PIORECR", "Iron Ore, US dollars per metric tonne, Unit prices", "铁矿石价格（IMF月均）",
          "U.S. dollars per metric ton", ("commodities",),
          ("iron ore price", "iron ore", "steel inputs", "铁矿石价格"), _PCPS_NOTE + " China import fines 62% Fe."),
    _pcps("PGOLD", "Gold, US dollars per troy ounce of gold, Unit prices", "黄金价格（IMF月均）",
          "U.S. dollars per troy ounce", ("commodities", "markets"), ("gold price", "gold", "金价", "黄金")),
    _pcps("PWHEAMT", "Wheat, US dollars per metric tonne, Unit prices", "小麦价格（IMF月均）",
          "U.S. dollars per metric ton", ("commodities",), ("wheat price", "wheat", "grain prices", "小麦价格")),
    _pcps("PMAIZMT", "Corn, US dollars per metric tonne, Unit prices", "玉米价格（IMF月均）",
          "U.S. dollars per metric ton", ("commodities",), ("corn price", "maize", "corn", "玉米价格")),
    _pcps("PSOYB", "Soybeans, US dollars per metric tonne, Unit prices", "大豆价格（IMF月均）",
          "U.S. dollars per metric ton", ("commodities", "trade"), ("soybean price", "soybeans", "大豆价格")),
    _pcps("PALLFNF", "All index, Commodity price index, Index, 2016=100", "IMF全部大宗商品价格指数",
          "Index 2016=100", ("commodities",),
          ("commodity price index", "commodity prices", "all commodities", "大宗商品价格指数", "大宗商品"),
          transformation="INDEX"),
    _pcps("PNRG", "Energy index, Commodity price index, Index, 2016=100", "IMF能源价格指数", "Index 2016=100",
          ("energy", "commodities"), ("energy price index", "energy prices", "能源价格指数"), transformation="INDEX"),
    _pcps("PMETA", "Base Metals index, Commodity price index, Index, 2016=100", "IMF基本金属价格指数",
          "Index 2016=100", ("commodities",), ("base metals index", "metal prices", "金属价格指数"),
          transformation="INDEX"),
    _pcps("PFOOD", "Food index, Commodity price index, Index, 2016=100", "IMF食品价格指数", "Index 2016=100",
          ("commodities", "inflation"), ("food price index", "food prices", "食品价格指数", "粮食价格"),
          transformation="INDEX"),
    # Consumer prices
    _imf_cpi("USA", "United States", "美国"),
    _imf_cpi("CHN", "China", "中国", ("deflation", "通缩")),
    _imf_cpi("DEU", "Germany", "德国"),
    _imf_cpi("JPN", "Japan", "日本"),
    _imf_cpi("GBR", "United Kingdom", "英国"),
    _imf_cpi("IND", "India", "印度"),
    _imf_cpi("BRA", "Brazil", "巴西"),
)


# ---------------------------------------------------------------------------
# World Bank Data360 (WDI history, IMF WEO country projections, WB GEP)
# ---------------------------------------------------------------------------

_WB_AREAS: dict[str, tuple[str, str]] = {
    "USA": ("United States", "美国"), "CHN": ("China", "中国"), "JPN": ("Japan", "日本"),
    "DEU": ("Germany", "德国"), "GBR": ("United Kingdom", "英国"), "IND": ("India", "印度"),
    "EMU": ("Euro area", "欧元区"), "WLD": ("World", "世界"),
}
_WB_WEO_NOTE = ("IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF "
                "projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163.")


def _wb_series(indicator: str, iso3: str, title: str, title_zh: str, units: str,
               topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "") -> CatalogEntry:
    name, name_zh = _WB_AREAS[iso3]
    return _wb(indicator, iso3, f"{title}: {name}", f"{name_zh}{title_zh}", units, topics, keywords, notes)


_WEO_GROWTH_KW = ("gdp growth", "economic growth", "real gdp growth", "growth forecast", "imf forecast",
                  "gdp增长", "经济增长", "增长率", "增速")
_WEO_CPI_KW = ("inflation", "cpi", "inflation forecast", "imf forecast", "通胀", "通货膨胀", "cpi通胀")
_WEO_LUR_KW = ("unemployment", "unemployment rate", "jobless rate", "失业率", "失业")
_WEO_DEBT_KW = ("government debt", "public debt", "debt to gdp", "sovereign debt", "政府债务", "债务占gdp", "国债")
_WEO_CA_KW = ("current account", "external balance", "trade surplus", "经常账户", "经常项目")

_WB_ENTRIES: tuple[CatalogEntry, ...] = (
    tuple(_wb_series("IMF_WEO_NGDP_RPCH", iso3, "Gross domestic product (GDP), Constant prices, Percent change",
                     "实际GDP增长率（IMF WEO）", "Percent change", ("growth", "projections"), _WEO_GROWTH_KW,
                     _WB_WEO_NOTE)
          for iso3 in ("USA", "CHN", "JPN", "DEU", "GBR", "IND"))
    + tuple(_wb_series("IMF_WEO_PCPIPCH", iso3, "All Items, Consumer price index (CPI), Period average, percent change",
                       "CPI通胀率（IMF WEO）", "Percent change", ("inflation", "projections"), _WEO_CPI_KW,
                       _WB_WEO_NOTE)
            for iso3 in ("USA", "CHN", "JPN", "DEU", "GBR", "IND"))
    + tuple(_wb_series("IMF_WEO_LUR", iso3, "Unemployment rate", "失业率（IMF WEO）", "Percent of labor force",
                       ("labor", "projections"), _WEO_LUR_KW,
                       _WB_WEO_NOTE + " Data360 labels the unit 'Percentage of population'; WEO defines it as "
                       "percent of the labor force.")
            for iso3 in ("USA", "CHN", "JPN", "DEU", "GBR"))
    + tuple(_wb_series("IMF_WEO_GGXWDG_NGDP", iso3, "Gross debt, General government, Percent of GDP",
                       "政府总债务占GDP比率（IMF WEO）", "Percent of GDP", ("fiscal", "projections"), _WEO_DEBT_KW,
                       _WB_WEO_NOTE)
            for iso3 in ("USA", "CHN", "JPN", "GBR"))
    + tuple(_wb_series("IMF_WEO_BCA_NGDPD", iso3, "Current account balance (credit less debit), Percent of GDP",
                       "经常账户余额占GDP比率（IMF WEO）", "Percent of GDP", ("trade", "projections"), _WEO_CA_KW,
                       _WB_WEO_NOTE)
            for iso3 in ("USA", "CHN", "DEU", "JPN"))
    + tuple(_wb_series("IMF_WEO_NGDPD", iso3, "Gross domestic product (GDP), Current prices, US dollar",
                       "名义GDP（美元，IMF WEO）", "U.S. dollars", ("growth", "projections"),
                       ("nominal gdp", "gdp in dollars", "economy size", "gdp size", "名义gdp", "经济总量", "gdp规模"),
                       _WB_WEO_NOTE + " Values are whole U.S. dollars although the metadata unit reads 'US dollars "
                       "(Billions)'; divide by 1e9 for billions.")
            for iso3 in ("USA", "CHN"))
    + tuple(_wb_series("WB_GEP_NYGDPMKTPKDZ", iso3,
                       "GDP growth, constant (average 2010-19 prices and market exchange rates)",
                       "GDP增长率（世界银行全球经济展望）", "Percent change per annum", ("growth", "projections"),
                       ("gdp growth", "growth forecast", "world bank forecast", "global economic prospects",
                        "gdp增长", "世界银行预测"),
                       "World Bank Global Economic Prospects: short window (about five years) whose final years "
                       "are World Bank forecasts. No world aggregate in Data360.")
            for iso3 in ("USA", "CHN", "IND", "EMU"))
    + tuple(_wb_series("WB_WDI_NY_GDP_MKTP_KD_ZG", iso3, "GDP (annual % growth)", "GDP年增长率（世界发展指标）",
                       "Percent", ("growth",),
                       ("gdp growth", "economic growth", "annual gdp growth", "historical growth", "gdp增长", "经济增长"),
                       "World Development Indicators history (actuals only); latest year lags one to two years.")
            for iso3 in ("USA", "CHN", "IND", "WLD"))
    + tuple(_wb_series("WB_WDI_SP_POP_TOTL", iso3, "Population, total", "总人口（世界发展指标）", "Persons",
                       ("population",), ("population", "demographics", "people", "人口", "总人口"),
                       "Mid-year estimates; latest year lags one to two years.")
            for iso3 in ("USA", "CHN", "IND", "WLD"))
    + tuple(_wb_series("WB_WDI_NY_GDP_PCAP_CD", iso3, "GDP per capita (current US$)", "人均GDP（现价美元）",
                       "Current U.S. dollars", ("growth", "income"),
                       ("gdp per capita", "income per person", "living standards", "人均gdp", "人均收入"))
            for iso3 in ("USA", "CHN", "IND"))
    + tuple(_wb_series("WB_WDI_EN_GHG_CO2_MT_CE_AR5", iso3,
                       "Carbon dioxide (CO2) emissions (total) excluding LULUCF (Mt CO2e)",
                       "二氧化碳排放总量（不含土地利用）", "Mt CO2 equivalent", ("climate", "energy"),
                       ("co2 emissions", "carbon emissions", "emissions", "greenhouse gas", "二氧化碳排放", "碳排放"),
                       "EDGAR-based estimates; latest year lags one to two years.")
            for iso3 in ("WLD", "CHN", "USA", "IND"))
    + tuple(_wb_series("WB_WDI_EG_USE_ELEC_KH_PC", iso3, "Electric power consumption (kWh per capita)",
                       "人均用电量", "Kilowatt-hours per capita", ("energy",),
                       ("electricity consumption", "power consumption", "electricity demand", "用电量", "电力消费"),
                       "Latest year lags one to two years.")
            for iso3 in ("CHN", "USA", "IND"))
    + (
        _wb_series("WB_WDI_FP_CPI_TOTL_ZG", "CHN", "Inflation, consumer prices (annual % growth)",
                   "CPI年通胀率（世界发展指标）", "Percent", ("inflation",),
                   ("inflation", "annual inflation", "consumer prices", "通胀", "通缩")),
        _wb_series("WB_WDI_FP_CPI_TOTL_ZG", "IND", "Inflation, consumer prices (annual % growth)",
                   "CPI年通胀率（世界发展指标）", "Percent", ("inflation",),
                   ("inflation", "annual inflation", "consumer prices", "通胀")),
        _wb_series("WB_WDI_NE_TRD_GNFS_ZS", "CHN", "Trade (% of GDP)", "贸易占GDP比重", "Percent of GDP", ("trade",),
                   ("trade openness", "trade to gdp", "贸易依存度", "贸易占gdp")),
        _wb_series("WB_WDI_NE_EXP_GNFS_ZS", "CHN", "Exports of goods and services (% of GDP)", "出口占GDP比重",
                   "Percent of GDP", ("trade",), ("exports to gdp", "export dependence", "出口依存度", "出口占gdp")),
        _wb_series("WB_WDI_SL_UEM_TOTL_ZS", "CHN", "Unemployment, total (% of total labor force) (modeled ILO estimate)",
                   "失业率（国际劳工组织模型估计）", "Percent of total labor force", ("labor",),
                   ("unemployment", "unemployment rate", "失业率"),
                   "Modeled ILO estimate; differs from China's surveyed urban unemployment rate."),
    )
)


# ---------------------------------------------------------------------------
# usgov (Treasury Fiscal Data, USAspending) -- recipes above
# ---------------------------------------------------------------------------

_DEBT_KW = ("national debt", "federal debt", "public debt", "debt ceiling", "us debt", "国债", "美国债务", "债务上限")
_MTS_KW = ("federal budget", "monthly treasury statement", "mts", "财政收支")

_USGOV_ENTRIES: tuple[CatalogEntry, ...] = (
    _usgov("treasury/debt_to_penny", ("fiscal",), _DEBT_KW + ("debt to the penny", "total public debt", "联邦债务")),
    _usgov("treasury/debt_held_public", ("fiscal",), _DEBT_KW + ("debt held by the public", "marketable debt", "公众持有债务")),
    _usgov("treasury/mts_deficit", ("fiscal",),
           _MTS_KW + ("budget deficit", "monthly deficit", "fiscal deficit", "deficit", "财政赤字", "赤字")),
    _usgov("treasury/mts_receipts", ("fiscal",),
           _MTS_KW + ("federal receipts", "tax revenue", "government revenue", "tax receipts", "财政收入", "税收")),
    _usgov("treasury/mts_outlays", ("fiscal",),
           _MTS_KW + ("federal outlays", "government spending", "federal spending", "财政支出", "政府支出")),
    _usgov("treasury/avg_interest_rate/Treasury Bills", ("fiscal", "rates"),
           ("interest cost", "cost of debt", "treasury bills", "average interest rate", "国债利率", "利息成本"),
           title_suffix="Treasury Bills", title_zh="美国国库券平均利率"),
    _usgov("treasury/avg_interest_rate/Treasury Notes", ("fiscal", "rates"),
           ("interest cost", "cost of debt", "treasury notes", "average interest rate", "国债利率", "利息成本"),
           title_suffix="Treasury Notes", title_zh="美国中期国债平均利率"),
    _usgov("treasury/avg_interest_rate/Treasury Bonds", ("fiscal", "rates"),
           ("interest cost", "cost of debt", "treasury bonds", "average interest rate", "国债利率"),
           title_suffix="Treasury Bonds", title_zh="美国长期国债平均利率"),
    _usgov("treasury/avg_interest_rate/Total Marketable", ("fiscal", "rates"),
           ("interest cost", "cost of debt", "average interest rate", "debt service cost", "interest expense",
            "利息成本", "付息成本"),
           title_suffix="Total Marketable", title_zh="美国可交易国债平均利率"),
    _usgov("treasury/avg_interest_rate/Total Interest-bearing Debt", ("fiscal", "rates"),
           ("interest cost", "average interest rate on debt", "interest expense", "付息债务平均利率"),
           title_suffix="Total Interest-bearing Debt", title_zh="美国全部付息债务平均利率"),
    _usgov("treasury/fx/Euro Zone-Euro", ("fx",), ("euro", "treasury exchange rate", "欧元汇率"),
           title_suffix="Euro Zone-Euro", title_zh="美国财政部报告汇率：欧元", geography="EMU"),
    _usgov("treasury/fx/China-Renminbi", ("fx",), ("renminbi", "yuan", "treasury exchange rate", "人民币汇率"),
           title_suffix="China-Renminbi", title_zh="美国财政部报告汇率：人民币", geography="CHN"),
    _usgov("treasury/fx/Japan-Yen", ("fx",), ("yen", "treasury exchange rate", "日元汇率"),
           title_suffix="Japan-Yen", title_zh="美国财政部报告汇率：日元", geography="JPN"),
    _usgov("treasury/fx/United Kingdom-Pound", ("fx",), ("pound", "sterling", "treasury exchange rate", "英镑汇率"),
           title_suffix="United Kingdom-Pound", title_zh="美国财政部报告汇率：英镑", geography="GBR"),
    _usgov("treasury/fx/Canada-Dollar", ("fx",), ("canadian dollar", "loonie", "treasury exchange rate", "加元汇率"),
           title_suffix="Canada-Dollar", title_zh="美国财政部报告汇率：加元", geography="CAN"),
    _usgov("treasury/fx/Mexico-Peso", ("fx",), ("peso", "treasury exchange rate", "比索汇率"),
           title_suffix="Mexico-Peso", title_zh="美国财政部报告汇率：墨西哥比索", geography="MEX"),
    _usgov("treasury/fx/India-Rupee", ("fx",), ("rupee", "treasury exchange rate", "卢比汇率"),
           title_suffix="India-Rupee", title_zh="美国财政部报告汇率：印度卢比", geography="IND"),
    _usgov("spending/total", ("fiscal",),
           ("federal spending", "government contracts", "federal awards", "grants", "usaspending", "联邦支出",
            "政府合同")),
)

CATALOG: tuple[CatalogEntry, ...] = (
    _FRED_ENTRIES + _BLS_ENTRIES + _BIS_ENTRIES + _IMF_ENTRIES + _WB_ENTRIES + _USGOV_ENTRIES
)

_BY_ID: dict[str, CatalogEntry] = {entry.series: entry for entry in CATALOG}
_BY_CASEFOLD: dict[str, CatalogEntry] = {entry.series.casefold(): entry for entry in CATALOG}
_INDEX: dict[str, int] = {entry.series: position for position, entry in enumerate(CATALOG)}

# Headline series: ranked ahead of near-ties in search, and shown in every planner
# digest when the question matches few entries.
_CORE_IDS: tuple[str, ...] = (
    "fred:A191RL1Q225SBEA", "fred:CPIAUCSL", "fred:PCEPILFE", "fred:UNRATE", "fred:PAYEMS",
    "fred:FEDFUNDS", "fred:DGS10", "fred:T10Y2Y", "fred:DCOILBRENTEU", "fred:DTWEXBGS",
    "bis:WS_CBPOL/M.XM", "bis:WS_CBPOL/M.CN", "imf:WEO/G001.NGDP_RPCH.A", "wb:IMF_WEO_NGDP_RPCH/CHN",
    "imf:PCPS/G001.PCOPP.USD.M", "usgov:treasury/debt_to_penny",
)
# Families preferred for forecasting when a concept matches (long official projections,
# cross-country policy rates) plus the headline ids above.
_PRIORITY_PREFIXES: tuple[str, ...] = (
    "wb:IMF_WEO_NGDP_RPCH/", "wb:IMF_WEO_PCPIPCH/", "wb:IMF_WEO_LUR/", "imf:WEO/", "bis:WS_CBPOL/",
)
_PRIORITY_IDS: frozenset[str] = frozenset(_CORE_IDS) | frozenset((
    "fred:CPILFESL", "fred:PCEPI", "fred:GDPC1", "fred:DFEDTARU", "fred:DGS2", "fred:DCOILWTICO",
    "fred:MORTGAGE30US", "fred:CSUSHPISA", "fred:ICSA", "fred:JTSJOL", "fred:BOPGSTB", "fred:GFDEGDQ188S",
    "bls:CUUR0000SA0", "bls:WPUFD4", "usgov:treasury/mts_deficit",
))
_PRIORITY_BONUS = 2.5
_PRIORITY_MIN_CONCEPT = 4.0   # one keyword-level match; topic or bigram overlap alone gets no bonus
_MIN_HIT_SCORE = 1.0          # drops lone CJK-bigram coincidences such as a shared "价格"


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def _canonical(series: str) -> str | None:
    text = (series or "").strip().strip("`'\"").strip()
    if ":" not in text:
        return None
    provider, native = text.split(":", 1)
    provider = provider.strip().lower()
    native = native.strip()
    if provider not in PROVIDERS or not native:
        return None
    if provider != "usgov":
        native = native.upper()
    return f"{provider}:{native}"


def lookup(series: str) -> CatalogEntry | None:
    """Catalog entry for an id such as ``"FRED:unrate"`` or `` `bis:WS_CBPOL/M.US` ``.

    The provider prefix is case-insensitive; native ids are upper-cased for every
    provider except usgov, whose recipes match case-insensitively.
    """
    canonical = _canonical(series)
    if canonical is None:
        return None
    if canonical.startswith("usgov:"):
        return _BY_CASEFOLD.get(canonical.casefold())
    return _BY_ID.get(canonical)


# ---------------------------------------------------------------------------
# Search (deterministic scoring over keywords, titles, topics and geography)
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[㐀-鿿]")
_WORD_RE = re.compile(r"[a-z0-9&]+")
_US_RE = re.compile(r"(?<![A-Za-z])U\.?S\.?A?(?![A-Za-z])")
_UK_RE = re.compile(r"(?<![A-Za-z])U\.?K\.?(?![A-Za-z])")
_STOPWORDS = frozenset((
    "a", "about", "above", "after", "all", "an", "and", "any", "are", "as", "at", "be", "before", "below",
    "between", "by", "can", "could", "data", "do", "does", "during", "each", "end", "for", "from", "has",
    "have", "how", "if", "in", "into", "is", "it", "its", "latest", "less", "level", "more", "most",
    "new", "next", "not", "of", "on", "or", "over", "per", "rate", "s", "series", "should", "than",
    "that", "the", "their", "this", "to", "total", "under", "until", "was", "what", "when", "which",
    "who", "will", "with", "would", "year", "years",
))


def _stem(word: str) -> str:
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


# Generic title words that say nothing about the concept ("Constant prices, Percent change").
_TITLE_NOISE = frozenset(_stem(word) for word in (
    "adjusted", "annual", "average", "basis", "change", "constant", "current", "daily", "dollars", "index",
    "monthly", "percent", "period", "prices", "quarterly", "seasonally", "units", "weekly",
))


def _ascii_words(text: str) -> list[str]:
    return [_stem(word) for word in _WORD_RE.findall(text.lower())]


def _phrase(text: str) -> str:
    return " ".join(_ascii_words(text))


def _cjk_bigrams(text: str) -> frozenset[str]:
    grams: set[str] = set()
    for run in re.findall(r"[㐀-鿿]+", text):
        grams.update(run[i:i + 2] for i in range(len(run) - 1))
    return frozenset(grams)


def _term_hit(term: str, padded: str, compact: str) -> bool:
    """True when ``term`` (an EN phrase or a CJK term) occurs in the query."""
    if _CJK_RE.search(term):
        return "".join(term.lower().split()) in compact
    phrase = _phrase(term)
    return bool(phrase) and f" {phrase} " in padded


_GEO_WORDS = frozenset(word for _name, aliases in GEOGRAPHIES.values() for alias in aliases
                       if not _CJK_RE.search(alias) for word in _ascii_words(alias))


@dataclass(frozen=True)
class _Query:
    raw_lower: str
    padded: str        # " stemmed ascii words "
    compact: str       # lowercase, whitespace removed (CJK substring matching)
    words: frozenset[str]
    bigrams: frozenset[str]
    geos: frozenset[str]


def _parse_query(query: str) -> _Query:
    raw = query or ""
    lowered = raw.lower()
    words = _ascii_words(raw)
    padded = f" {' '.join(words)} "
    compact = "".join(lowered.split())
    geos = set()
    if _US_RE.search(raw):
        geos.add("USA")
    if _UK_RE.search(raw):
        geos.add("GBR")
    for code, (_name, aliases) in GEOGRAPHIES.items():
        if any(_term_hit(alias, padded, compact) for alias in aliases):
            geos.add(code)
    concept_words = frozenset(word for word in words
                              if word not in _STOPWORDS and word not in _GEO_WORDS and not word.isdigit())
    return _Query(raw_lower=lowered, padded=padded, compact=compact, words=concept_words,
                  bigrams=_cjk_bigrams(raw), geos=frozenset(geos))


@dataclass(frozen=True)
class _EntryTerms:
    title_words: frozenset[str]
    zh_bigrams: frozenset[str]
    native_lower: str


_ENTRY_TERMS: dict[str, _EntryTerms] = {
    entry.series: _EntryTerms(
        title_words=frozenset(word for word in _ascii_words(entry.title)
                              if word not in _STOPWORDS and word not in _GEO_WORDS and word not in _TITLE_NOISE
                              and not word.isdigit() and len(word) > 2),
        zh_bigrams=_cjk_bigrams(entry.title_zh),
        native_lower=entry.native.lower(),
    )
    for entry in CATALOG
}


def _concept_score(entry: CatalogEntry, query: _Query) -> float:
    terms = _ENTRY_TERMS[entry.series]
    score = 0.0
    if entry.series.lower() in query.raw_lower:
        score += 100.0
    elif len(terms.native_lower) >= 5 and re.search(
            rf"(?<![a-z0-9_]){re.escape(terms.native_lower)}(?![a-z0-9_])", query.raw_lower):
        score += 40.0
    for keyword in entry.keywords:
        if _term_hit(keyword, query.padded, query.compact):
            if _CJK_RE.search(keyword):
                score += 4.0 + 0.5 * max(0, len(keyword) - 2)
            else:
                score += 4.0 + 1.5 * (len(keyword.split()) - 1)
    score += 1.0 * min(3, len(terms.title_words & query.words))
    score += 0.75 * min(6, len(terms.zh_bigrams & query.bigrams))
    for topic in entry.topics:
        if any(_term_hit(term, query.padded, query.compact) for term in TOPICS[topic]):
            score += 2.0
    return score


def _priority(entry: CatalogEntry) -> bool:
    return entry.series in _PRIORITY_IDS or entry.series.startswith(_PRIORITY_PREFIXES)


def _score(entry: CatalogEntry, query: _Query) -> float:
    concept = _concept_score(entry, query)
    if concept >= _PRIORITY_MIN_CONCEPT and _priority(entry):
        concept += _PRIORITY_BONUS
    if not query.geos:
        return concept
    if entry.geography in query.geos:
        # A strong concept match in the asked-about economy wins; a topic-only match barely
        # moves; a bare place name ("China") lists that economy's series.
        if concept >= _PRIORITY_MIN_CONCEPT:
            return concept + 6.0
        if concept > 0:
            return concept + 1.0
        return 0.0 if query.words else 1.0
    if entry.geography == "WLD":
        return concept
    return concept * 0.35


def _ranked(query: str, provider: str | None) -> list[tuple[float, CatalogEntry]]:
    if not (query or "").strip():
        return []
    wanted = (provider or "").strip().lower() or None
    if wanted is not None and wanted not in PROVIDERS:
        return []
    parsed = _parse_query(query)
    scored = []
    for entry in CATALOG:
        if wanted is not None and entry.provider != wanted:
            continue
        score = round(_score(entry, parsed), 6)
        if score >= _MIN_HIT_SCORE:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], _INDEX[item[1].series]))
    return scored


def search_catalog(query: str, *, provider: str | None = None, limit: int = 8) -> list[CatalogEntry]:
    """Catalog entries ranked for ``query`` (EN or ZH); ties keep catalog order.

    ``provider`` restricts the search to one provider id; an unknown provider or an
    empty query returns [].
    """
    if limit <= 0:
        return []
    return [entry for _score_value, entry in _ranked(query, provider)[:limit]]


# ---------------------------------------------------------------------------
# Planner digest and skill reference
# ---------------------------------------------------------------------------

_DIGEST_MAX_CHARS = 6000
_DIGEST_TITLE_MAX = 90


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _digest_line(entry: CatalogEntry) -> str:
    facets = [entry.units, entry.frequency]
    if entry.seasonal_adjustment:
        facets.append(entry.seasonal_adjustment)
    facets.append(entry.geography)
    return f"- {entry.series} — {_clip(entry.title, _DIGEST_TITLE_MAX)} ({', '.join(facets)})"


def catalog_digest(question: str, *, limit: int = 40) -> str:
    """Compact, deterministic provider overview + the catalog entries most relevant
    to ``question`` (headline series fill in when few match).  At most ~6,000 chars."""
    limit = max(1, int(limit))
    header = ["OFFICIAL DATA PROVIDERS (series id = provider:native id; data_search finds ids, "
              "data_get fetches a citable series):"]
    for pid, meta in PROVIDERS.items():
        header.append(f"- {pid}: {meta['name']} — {meta['role']}. Example: {meta['example']}")
    header.append("Any FRED series id also works as fred:<ID>; BIS, IMF, World Bank and usgov ids must come "
                  "from this list or data_search.")
    picked = [entry for score, entry in _ranked(question, None) if score >= _PRIORITY_MIN_CONCEPT][:limit]
    seen = {entry.series for entry in picked}
    filler = [_BY_ID[sid] for sid in _CORE_IDS if sid not in seen][:max(0, limit - len(picked))]
    lines = header + ["", "CATALOG SERIES (id — title (units, frequency, seasonal adjustment, geography)):"]
    lines += [_digest_line(entry) for entry in picked + filler]
    while len("\n".join(lines)) > _DIGEST_MAX_CHARS and len(lines) > len(header) + 3:
        lines.pop()
    return "\n".join(lines)


def _cell(text: str, limit: int | None = None) -> str:
    value = " ".join(str(text).split()).replace("|", "\\|")
    return _clip(value, limit) if limit else value


def render_catalog_markdown() -> str:
    """Full markdown body of ``skills/data-sources/references/series-catalog.md``."""
    counts = {pid: sum(1 for entry in CATALOG if entry.provider == pid) for pid in PROVIDERS}
    out = [
        "# Official data series catalog",
        "",
        "Generated from `deerflow_bridge/data_catalog.py` by `render_catalog_markdown()`; do not edit by hand "
        "(regenerate with `python deerflow_bridge/data_catalog.py --write-markdown`).",
        "",
        f"{len(CATALOG)} curated series across {len(PROVIDERS)} providers. Every id was verified live on "
        f"{VERIFIED_ON}: the provider returned recent data, and titles and units come from its own metadata. "
        "Pass an id exactly as written to `data_get`; `data_search` searches this catalog first.",
        "",
        "Columns: Freq D/W/M/Q/A = daily/weekly/monthly/quarterly/annual; SA = seasonally adjusted, "
        "SAAR = seasonally adjusted annual rate, NSA = not seasonally adjusted, blank = not applicable or "
        "not published; Geo = ISO3 code, EMU = euro area, WLD = world or global benchmark.",
        "",
        "## Providers",
        "",
        "| Provider | Source | Use for | Example id | Series |",
        "|---|---|---|---|---|",
    ]
    for pid, meta in PROVIDERS.items():
        out.append(f"| {pid} | {_cell(meta['name'])} | {_cell(meta['role'])} | `{meta['example']}` | {counts[pid]} |")
    for pid, meta in PROVIDERS.items():
        out += ["", f"## {pid} — {meta['name']}", "",
                "| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |",
                "|---|---|---|---|---|---|---|---|"]
        for entry in CATALOG:
            if entry.provider != pid:
                continue
            out.append(
                f"| `{entry.series}` | {_cell(entry.title, 140)} | {_cell(entry.title_zh)} | {_cell(entry.units)} "
                f"| {entry.frequency} | {entry.seasonal_adjustment} | {entry.geography} | {_cell(entry.notes, 220)} |")
    out += ["", "## BIS dataflows (ids are `bis:<FLOW>/<KEY>`; key parts follow the dimension order)", "",
            "| Flow | Version | Key dimensions (in order) | Citation topic | Title |", "|---|---|---|---|---|"]
    for flow, meta in BIS_FLOWS.items():
        out.append(f"| {flow} | {meta['version']} | {'.'.join(meta['dims'])} | {meta['topic']} | {meta['title']} |")
    out += ["", "## IMF dataflows (ids are `imf:<FLOW>/<KEY>`)", "",
            "| Flow | Agency | Key dimensions (in order) | Title |", "|---|---|---|---|"]
    for flow, meta in IMF_FLOWS.items():
        out.append(f"| {flow} | {meta['agency']} | {'.'.join(meta['dims'])} | {meta['title']} |")
    out += ["", "WEO vintages follow `WEO_<YYYY>_<APR|OCT>_VINTAGE` with the WEO key layout.",
            "", "## usgov recipes (ids are `usgov:<recipe>[/<parameter>]`)", "",
            "| Recipe | Title | Tool | Endpoint | Value field | Freq | Units | Parameter | Notes |",
            "|---|---|---|---|---|---|---|---|---|"]
    for key, recipe in USGOV_RECIPES.items():
        out.append(
            f"| `{key}` | {_cell(recipe['title'])} | {recipe['tool']} | `{recipe['endpoint']}` | {recipe['value_field']} "
            f"| {recipe['frequency']} | {_cell(recipe['units'])} | {_cell(recipe['param_format'])} "
            f"| {_cell(recipe['notes'], 220)} |")
    return "\n".join(out) + "\n"


def _default_markdown_path() -> Path:
    return Path(__file__).resolve().parent / "skills" / "data-sources" / "references" / "series-catalog.md"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["--write-markdown"] or len(args) > 2:
        print("usage: data_catalog.py --write-markdown [PATH]", file=sys.stderr)
        return 2
    target = Path(args[1]) if len(args) == 2 else _default_markdown_path()
    if not target.parent.is_dir():
        print(f"error: directory does not exist: {target.parent}", file=sys.stderr)
        return 1
    target.write_text(render_catalog_markdown(), encoding="utf-8")
    print(f"wrote {target} ({len(CATALOG)} series)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
