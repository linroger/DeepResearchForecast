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
  verified live against the provider on ``VERIFIED_ON`` or, when added later,
  on the day it was added (data rows returned for a recent period; titles and
  units taken from the provider's own metadata).  Ids follow the agent-facing
  grammar ``<provider>:<native>``.
  World Bank and BIS rows also pin the verified native unit identity
  (``native_unit`` / ``native_dims``), so the data layer checks codes instead
  of comparing free-text labels and always shows the curated ``units``.
* ``BIS_FLOWS`` / ``IMF_FLOWS`` describe the SDMX dataflows the BIS and IMF
  ids use (version, ordered key dimensions, citation page); ``USGOV_RECIPES``
  describes the fixed Treasury / USAspending / EIA / BEA queries behind
  ``usgov:<recipe>`` ids, including the row keys that stop the Treasury API
  from silently summing rows.  EIA and BEA recipes need ``EIA_API_KEY`` /
  ``BEA_API_KEY`` (the us-gov server loads those modules only with a key) and
  are advertised only when the key is set.
* :func:`lookup`, :func:`search_catalog_scored` / :func:`search_catalog` and
  :func:`catalog_digest` are the deterministic helpers used by
  ``data_sources`` (search hits), the v3 planner (digest) and the skill
  reference (:func:`render_catalog_files`, the generator of
  ``skills/data-sources/references/*.md``).

Pure data plus small helpers: stdlib only, no I/O at import, so the module
imports in both the backend venv and the deer-flow venv.  Regenerate the skill
reference after editing the catalog::

    python deerflow_bridge/data_catalog.py --write-markdown
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

__all__ = [
    "AGGREGATIONS",
    "BIS_FLOWS",
    "CATALOG",
    "CatalogEntry",
    "CatalogHit",
    "ConceptTerms",
    "FREQUENCIES",
    "FREQUENCY_LABELS",
    "IMF_FLOWS",
    "PROVIDERS",
    "REFERENCE_INDEX",
    "SEASONAL_ADJUSTMENTS",
    "STATUS_POLICIES",
    "STRONG_CONCEPT_SCORE",
    "TOPICS",
    "USGOV_PUBLISHERS",
    "USGOV_RECIPES",
    "VERIFIED_ON",
    "WB_DATABASES",
    "WB_UNSUPPORTED_NOTE",
    "catalog_digest",
    "concept_terms",
    "english_query",
    "entry_available",
    "imf_flow_info",
    "lookup",
    "provider_name",
    "query_geographies",
    "recipe_available",
    "render_catalog_files",
    "resolve_usgov_recipe",
    "search_catalog",
    "search_catalog_scored",
    "shares_concept",
    "wb_database",
]

VERIFIED_ON = "2026-10-12"

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
                 "vintages; slow (30-60 s per call): prefer a listed faster equivalent, otherwise prefetch"),
        "example": "imf:PCPS/G001.POILBRE.USD.M",
    },
    "wb": {
        "name": "World Bank Data360",
        "role": ("annual cross-country history (World Development Indicators) and official "
                 "projections: IMF WEO by country to 2031, World Bank Global Economic Prospects"),
        "example": "wb:IMF_WEO_NGDP_RPCH/CHN",
    },
    "usgov": {
        "name": "U.S. Government Open Data (Treasury Fiscal Data, USAspending, EIA, BEA)",
        "role": ("federal debt to the penny, monthly receipts (customs duties, income taxes), outlays, "
                 "gross interest and deficit, average interest rate on Treasury debt, Treasury reporting "
                 "exchange rates, federal award spending"),
        "example": "usgov:treasury/mts_deficit",
    },
}

# Keyed usgov modules: the us-gov server loads them only when the key is set
# (data_mcp.USGOV_KEYED_MODULES), so their recipes are advertised only then.
_KEYED_ROLES: dict[str, str] = {
    "EIA_API_KEY": ("EIA electricity retail sales and prices by state and sector, net generation by fuel, "
                    "generating capacity incl. batteries, crude oil production"),
    "BEA_API_KEY": "BEA national accounts (real GDP and PCE growth, personal income) and value added by industry",
}

# The agency that publishes a usgov recipe's data (by recipe kind): a fetched usgov series names
# it as its provider_name, not the gateway name above.  The part before " (" is the short form
# the snapshot and the chart footers (render_data._SOURCE_PREFIXES) show.
USGOV_PUBLISHERS: dict[str, str] = {
    "treasury": "U.S. Treasury Fiscal Data (Bureau of the Fiscal Service)",
    "usaspending": "USAspending.gov (U.S. Department of the Treasury)",
    "eia": "U.S. Energy Information Administration (EIA)",
    "bea_nipa": "U.S. Bureau of Economic Analysis (BEA)",
    "bea_industry": "U.S. Bureau of Economic Analysis (BEA)",
    "sec": "U.S. Securities and Exchange Commission (SEC)",
}


def provider_name(provider: str, native: str = "") -> str:
    """Publisher name a fetched series carries: the provider's, or for a usgov recipe the
    agency that publishes it (EIA, BEA, Treasury Fiscal Data, USAspending)."""
    if provider == "usgov":
        recipe = resolve_usgov_recipe(native)
        publisher = USGOV_PUBLISHERS.get(recipe[1]["kind"], "") if recipe else ""
        if publisher:
            return publisher
    return PROVIDERS[provider]["name"]


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
    "energy": ("energy", "oil", "gas", "electricity", "power", "power grid", "electricity demand",
               "electricity consumption", "power consumption", "energy consumption", "electricity sales",
               "electricity price", "electricity prices", "power price", "power prices", "retail electricity",
               "electricity retail", "power generation", "renewable", "renewables", "solar", "wind power", "nuclear",
               "energy storage", "battery storage", "能源", "石油", "原油", "天然气", "电力", "电网", "发电",
               "用电", "储能", "可再生能源", "光伏", "风电", "核电"),
    "commodities": ("commodity", "commodities", "metal", "metals", "大宗商品", "金属"),
    "fiscal": ("fiscal", "budget", "deficit", "government debt", "public debt", "treasury",
               "财政", "赤字", "政府债务"),
    "trade": ("trade", "exports", "imports", "tariff", "tariffs", "customs", "customs duties", "trade war",
              "贸易", "出口", "进口", "关税", "海关", "贸易战"),
    "technology": ("semiconductor", "semiconductors", "chip", "chips", "chipmaker", "electronics",
                   "data center", "data centers", "datacenter", "artificial intelligence", "ai",
                   "cloud computing", "半导体", "芯片", "集成电路", "数据中心", "人工智能", "算力", "电子"),
    "autos": ("vehicle", "vehicles", "car", "cars", "auto", "autos", "automobile", "electric vehicle",
              "electric vehicles", "new energy vehicle", "new energy vehicles", "ev", "evs", "nev", "nevs",
              "汽车", "新能源汽车", "电动汽车"),
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

# Geography codes used by the catalog and the Data360 economies its search and labels name ->
# (English name, aliases EN + ZH) for query matching.  The English name is itself an alias and the
# first CJK alias is the Chinese name (data_sources.series_label; mirrored in data-visuals
# render_data._GEOGRAPHIES).  "WLD" marks global benchmarks (commodity prices, world aggregates):
# neutral for country queries.  No alias contains the word "bank" (central banks go by their
# acronyms), so "World Bank" or "central bank" never names a place.
GEOGRAPHIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "USA": ("United States", ("united states", "america", "american", "usa", "federal reserve",
                              "fed", "fomc", "美国", "美联储")),
    "CHN": ("China", ("china", "chinese", "prc", "pboc", "中国", "人民银行", "人民币")),
    "EMU": ("Euro area", ("euro area", "eurozone", "euro zone", "europe", "european", "ecb",
                          "欧元区", "欧洲", "欧洲央行", "欧央行")),
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
    "FRA": ("France", ("france", "french", "法国")),
    "ITA": ("Italy", ("italy", "italian", "意大利")),
    "ESP": ("Spain", ("spain", "spanish", "西班牙")),
    "NLD": ("Netherlands", ("netherlands", "dutch", "holland", "荷兰")),
    "BEL": ("Belgium", ("belgium", "belgian", "比利时")),
    "AUT": ("Austria", ("austria", "austrian", "奥地利")),
    "IRL": ("Ireland", ("ireland", "irish", "爱尔兰")),
    "PRT": ("Portugal", ("portugal", "portuguese", "葡萄牙")),
    "GRC": ("Greece", ("greece", "greek", "希腊")),
    "FIN": ("Finland", ("finland", "finnish", "芬兰")),
    "SWE": ("Sweden", ("sweden", "swedish", "riksbank", "瑞典")),
    "NOR": ("Norway", ("norway", "norwegian", "挪威")),
    "DNK": ("Denmark", ("denmark", "danish", "丹麦")),
    "POL": ("Poland", ("poland", "波兰")),
    "CZE": ("Czechia", ("czechia", "czech republic", "czech", "捷克")),
    "HUN": ("Hungary", ("hungary", "hungarian", "匈牙利")),
    "ROU": ("Romania", ("romania", "romanian", "罗马尼亚")),
    "UKR": ("Ukraine", ("ukraine", "ukrainian", "乌克兰")),
    "RUS": ("Russia", ("russia", "russian federation", "russian", "俄罗斯")),
    "TUR": ("Türkiye", ("türkiye", "turkiye", "turkey", "turkish", "土耳其")),
    "ISR": ("Israel", ("israel", "israeli", "以色列")),
    "IRN": ("Iran", ("iran", "iranian", "伊朗")),
    "SAU": ("Saudi Arabia", ("saudi arabia", "saudi", "沙特阿拉伯", "沙特")),
    "EGY": ("Egypt", ("egypt", "egyptian", "埃及")),
    "NGA": ("Nigeria", ("nigeria", "nigerian", "尼日利亚")),
    "ZAF": ("South Africa", ("south africa", "south african", "南非")),
    "ARG": ("Argentina", ("argentina", "argentine", "argentinian", "阿根廷")),
    "CHL": ("Chile", ("chile", "chilean", "智利")),
    "COL": ("Colombia", ("colombia", "colombian", "哥伦比亚")),
    "PAK": ("Pakistan", ("pakistan", "pakistani", "巴基斯坦")),
    "BGD": ("Bangladesh", ("bangladesh", "bangladeshi", "孟加拉国", "孟加拉")),
    "IDN": ("Indonesia", ("indonesia", "indonesian", "印度尼西亚", "印尼")),
    "VNM": ("Vietnam", ("vietnam", "viet nam", "vietnamese", "越南")),
    "THA": ("Thailand", ("thailand", "thai", "泰国")),
    "MYS": ("Malaysia", ("malaysia", "malaysian", "马来西亚")),
    "PHL": ("Philippines", ("philippines", "philippine", "filipino", "菲律宾")),
    "SGP": ("Singapore", ("singapore", "singaporean", "新加坡")),
    "TWN": ("Taiwan, China", ("taiwan, china", "taiwan", "taiwanese", "中国台湾", "台湾")),
    "HKG": ("Hong Kong SAR, China", ("hong kong sar, china", "hong kong", "中国香港", "香港")),
    "NZL": ("New Zealand", ("new zealand", "rbnz", "新西兰")),
    "WLD": ("World", ("world", "global", "worldwide", "全球", "世界")),
}

# Publishers, international organisations and their flagship publications name who states a
# statistic, never a place or a concept: a China question "drawing on IMF and World Bank
# forecasts" stays a China question, and the "货币" of 国际货币基金组织 is no currency topic.
# They are removed before geographies, topics and concept terms are read; keyword scoring still
# sees them ("imf forecast", "世界银行预测").  Acronyms that are also English words (UN, WHO, BIS)
# count only in capitals.
_PUBLISHER_NAMES: tuple[str, ...] = (
    "world bank group", "world bank", "international monetary fund", "imf", "world trade organization",
    "world trade organisation", "wto", "organisation for economic co-operation and development",
    "organization for economic cooperation and development", "oecd", "united nations", "unctad",
    "bank for international settlements", "international energy agency", "iea",
    "world semiconductor trade statistics", "wsts", "world economic outlook", "global economic prospects",
    "world development indicators", "world economic forum", "world health organization",
)
_PUBLISHER_ACRONYMS: tuple[str, ...] = ("UN", "WHO", "BIS", "WEO", "GEP", "WDI", "WEF")
_PUBLISHERS_ZH: tuple[str, ...] = (
    "世界银行", "国际货币基金组织", "国际货币基金", "世界贸易组织", "世贸组织", "经济合作与发展组织", "经合组织",
    "联合国", "国际清算银行", "国际能源署", "国际能源机构", "世界半导体贸易统计组织", "世界经济展望",
    "全球经济展望", "世界发展指标", "世界经济论坛", "世界卫生组织",
)

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
# database is the indicator's first two underscore-separated parts.  Only these carry a
# verified unit and status policy; a search hit from any other Data360 database is
# reported with WB_UNSUPPORTED_NOTE instead of being dropped silently.
WB_DATABASES: tuple[str, ...] = ("WB_WDI", "IMF_WEO", "WB_GEP")
WB_UNSUPPORTED_NOTE = ("Not fetchable: Data360 database without a verified unit/status policy "
                       "(fetchable: WB_WDI, IMF_WEO, WB_GEP).")

_TREASURY_API = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
_MTS_FIELDS = "record_date,line_code_nbr,src_line_nbr,classification_desc,current_month_rcpt_outly_amt"
_MTS_ROW_NOTE = "MTS Table 3 row selected by line_code_nbr (stable; src_line_nbr drifts between years)."
_MTS_NOTE = (_MTS_ROW_NOTE + " Strong monthly seasonality (April and September receipts); compare with the same "
             "month a year earlier or use fiscal-year-to-date totals.")
_MTS_URL = "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/"
_EIA_API = "https://api.eia.gov/v2"
_EIA_BROWSER = "https://www.eia.gov/electricity/data/browser/"
_BEA_API = "https://apps.bea.gov/api/data/"

AGGREGATIONS: tuple[str, ...] = ("avg", "eop", "")
STATUS_POLICIES: tuple[str, ...] = ("", "history_only", "weo_vintage", "gep_vintage")

# usgov:<recipe>[/<param>] -> fixed query.  Every recipe carries every key below
# ("" / () / {} / 0 = not applicable), so one adapter can dispatch on ``kind``:
#   kind               treasury | usaspending | sec | eia | bea_nipa | bea_industry
#   tool, tool_args    usgov MCP tool and its fixed arguments; callers add the window and paging
#   endpoint, api_url  Treasury endpoint; citable API URL (never carries a key)
#   fields, filters, sort   Treasury query: callers append "record_date:gte:<start>" to filters
#                      and choose page_size; fields always include the row key so the Fiscal
#                      Data API never sums rows that share the selected columns
#   date_field, value_field, period_format   row keys of period and value; native period text
#                      (YYYY-MM-DD, YYYY-MM, YYYY, YYYYQn, or YYYYQ<roman> as in "2025QIV")
#   param_field        treasury: the id suffix becomes "<param_field>:eq:<param>" (appended to
#                      filters); bea_industry: the tool argument that receives the suffix
#   param_facets       eia: the "."-separated suffix parts become these facet values
#   param_format, param_examples, param_pattern   suffix grammar (pattern = full match)
#   tiebreak_field     rows sharing a date are amendments -- keep the smallest tiebreak value
#   facets             eia: fixed facet pins; every returned row must carry these values
#   units_field, native_units   eia: row key holding the unit and its verified exact text
#   line_description   bea_nipa: the one table line kept (exactly one line must match)
#   max_obs_per_call   bea: the tool returns at most this many observations per line and call,
#                      so callers chunk the window by years and never reach the cap
#   aggregation        eop | avg | "" -- how a native-daily series becomes monthly
#   min_start          earliest valid start; clamp the window before calling
#   requires_key       env var the usgov module needs; the recipe is advertised only when set
#   enabled            False = known recipe the supplied handler cannot serve (never advertised)
_RECIPE_DEFAULTS: dict[str, Any] = {
    "kind": "treasury", "title": "", "title_zh": "", "tool": "treasury_query_fiscal_data", "tool_args": {},
    "endpoint": "", "api_url": "", "fields": "", "filters": "", "sort": "-record_date",
    "date_field": "record_date", "value_field": "", "period_format": "YYYY-MM-DD",
    "param_field": "", "param_facets": (), "param_format": "", "param_examples": (), "param_pattern": "",
    "tiebreak_field": "", "facets": {}, "units_field": "", "native_units": "", "line_description": "",
    "max_obs_per_call": 0, "frequency": "", "seasonal_adjustment": "", "units": "", "source_url": "",
    "notes": "", "aggregation": "", "min_start": "", "requires_key": "", "enabled": True,
}


def _recipe(**values: Any) -> dict[str, Any]:
    unknown = sorted(set(values) - set(_RECIPE_DEFAULTS))
    if unknown:
        raise ValueError(f"unknown usgov recipe keys: {unknown}")
    recipe = {**_RECIPE_DEFAULTS, **values}
    recipe["tool_args"] = dict(recipe["tool_args"])
    recipe["facets"] = dict(recipe["facets"])
    return recipe


def _mts(line: str, title: str, title_zh: str, notes: str = _MTS_NOTE) -> dict[str, Any]:
    return _recipe(title=f"Monthly Treasury Statement: {title} (current month)", title_zh=title_zh,
                   endpoint="/v1/accounting/mts/mts_table_3", api_url=f"{_TREASURY_API}/v1/accounting/mts/mts_table_3",
                   fields=_MTS_FIELDS, filters=f"line_code_nbr:eq:{line}", value_field="current_month_rcpt_outly_amt",
                   frequency="M", seasonal_adjustment="NSA", units="U.S. dollars", source_url=_MTS_URL, notes=notes)


def _eia(route: str, data: str, frequency: str, **values: Any) -> dict[str, Any]:
    tool_frequency = {"M": "monthly", "A": "annual"}[frequency]
    return _recipe(kind="eia", tool="eia_query", tool_args={"route": route, "data": data, "frequency": tool_frequency},
                   endpoint=f"/{route}/data/", api_url=f"{_EIA_API}/{route}/data/", sort="", date_field="period",
                   value_field=data, period_format="YYYY-MM" if frequency == "M" else "YYYY", frequency=frequency,
                   seasonal_adjustment="NSA" if frequency == "M" else "", requires_key="EIA_API_KEY", **values)


def _bea_nipa(table: str, line: str, units: str, **values: Any) -> dict[str, Any]:
    return _recipe(kind="bea_nipa", tool="bea_gdp_national", tool_args={"table_name": table, "frequency": "Q"},
                   endpoint=f"NIPA/{table}", sort="", date_field="period", value_field="value",
                   api_url=f"{_BEA_API}?method=GetData&DataSetName=NIPA&TableName={table}&Frequency=Q",
                   period_format="YYYYQn", line_description=line, max_obs_per_call=8, frequency="Q",
                   seasonal_adjustment="SAAR", units=units,
                   source_url="https://www.bea.gov/itable/national-gdp-and-personal-income",
                   requires_key="BEA_API_KEY", **values)


USGOV_RECIPES: dict[str, dict[str, Any]] = {
    "treasury/debt_to_penny": _recipe(
        title="Debt to the Penny: Total Public Debt Outstanding", title_zh="美国联邦公共债务总额（每日）",
        endpoint="/v2/accounting/od/debt_to_penny", api_url=f"{_TREASURY_API}/v2/accounting/od/debt_to_penny",
        fields="record_date,tot_pub_debt_out_amt", value_field="tot_pub_debt_out_amt", frequency="D",
        units="U.S. dollars", source_url="https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/",
        notes="Business-day series; includes intragovernmental holdings (use debt_held_public for market debt).",
        aggregation="eop"),
    "treasury/debt_held_public": _recipe(
        title="Debt to the Penny: Debt Held by the Public", title_zh="美国公众持有的联邦债务（每日）",
        endpoint="/v2/accounting/od/debt_to_penny", api_url=f"{_TREASURY_API}/v2/accounting/od/debt_to_penny",
        fields="record_date,debt_held_public_amt", value_field="debt_held_public_amt", frequency="D",
        units="U.S. dollars", source_url="https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/",
        notes="Excludes intragovernmental holdings such as the Social Security trust funds.", aggregation="eop"),
    "treasury/mts_receipts": _mts("130", "Total Receipts", "美国联邦财政月度总收入"),
    "treasury/mts_outlays": _mts("490", "Total Outlays", "美国联邦财政月度总支出"),
    "treasury/mts_deficit": _mts("520", "Surplus (+) or Deficit (-)", "美国联邦财政月度盈余（+）或赤字（-）",
                                 "Negative values are deficits. " + _MTS_NOTE),
    "treasury/mts_customs_duties": _mts("110", "Customs Duties", "美国关税收入（月度）",
                                        "Net of refunds, so a month can be negative (July 2026: -$8.5 billion). "
                                        + _MTS_NOTE),
    "treasury/mts_individual_income_taxes": _mts("20", "Individual Income Taxes", "美国个人所得税收入（月度）"),
    "treasury/mts_corporation_income_taxes": _mts("30", "Corporation Income Taxes", "美国企业所得税收入（月度）",
                                                  "Quarterly estimated-tax months dominate. " + _MTS_NOTE),
    "treasury/mts_interest_gross": _mts("360", "Interest on Treasury Debt Securities (Gross)",
                                        "美国国债利息支出（总额，月度）",
                                        "Outlay line: gross interest including interest credited to trust funds "
                                        "(net interest is lower). " + _MTS_ROW_NOTE),
    "treasury/avg_interest_rate": _recipe(
        title="Average Interest Rates on U.S. Treasury Securities", title_zh="美国国债平均利率",
        endpoint="/v2/accounting/od/avg_interest_rates", api_url=f"{_TREASURY_API}/v2/accounting/od/avg_interest_rates",
        fields="record_date,security_type_desc,security_desc,avg_interest_rate_amt",
        value_field="avg_interest_rate_amt", param_field="security_desc", param_format="<security_desc>",
        param_examples=("Treasury Bills", "Treasury Notes", "Treasury Bonds",
                        "Treasury Inflation-Protected Securities (TIPS)", "Total Marketable",
                        "Total Interest-bearing Debt"),
        frequency="M", units="Percent",
        source_url="https://fiscaldata.treasury.gov/datasets/average-interest-rates-treasury-securities/",
        notes="Average rate on outstanding debt (a slow-moving cost of debt), not a market yield."),
    "treasury/fx": _recipe(
        title="Treasury Reporting Rates of Exchange", title_zh="美国财政部报告汇率",
        endpoint="/v1/accounting/od/rates_of_exchange", api_url=f"{_TREASURY_API}/v1/accounting/od/rates_of_exchange",
        fields="record_date,country_currency_desc,exchange_rate,effective_date", value_field="exchange_rate",
        param_field="country_currency_desc", param_format="<country_currency_desc>",
        param_examples=("Euro Zone-Euro", "China-Renminbi", "Japan-Yen", "United Kingdom-Pound",
                        "Canada-Dollar", "Mexico-Peso", "India-Rupee"),
        tiebreak_field="effective_date", frequency="Q", units="Foreign currency units per U.S. dollar",
        source_url="https://fiscaldata.treasury.gov/datasets/treasury-reporting-rates-exchange/",
        notes=("Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter "
               "amendment (later effective_date); the quarter-end rate is the earliest effective_date.")),
    "spending/total": _recipe(
        kind="usaspending", title="USAspending: Federal Award Spending by Fiscal Year",
        title_zh="美国联邦奖励支出（按财年）", tool="usa_spending_over_time", tool_args={"group": "fiscal_year"},
        endpoint="https://api.usaspending.gov/api/v2/search/spending_over_time/",
        api_url="https://api.usaspending.gov/api/v2/search/spending_over_time/", sort="", date_field="periodStart",
        value_field="amount", frequency="A", units="U.S. dollars", source_url="https://www.usaspending.gov/explorer",
        notes=("Award obligations (contracts, grants, loans, direct payments), not total budget outlays; "
               "periodStart is the first month of the fiscal year (FY2025 starts 2024-10). Recent years "
               "rise as agencies report late."),
        min_start="2007-10-01"),
    "sec": _recipe(
        kind="sec", title="SEC XBRL company concept (company facts)", title_zh="SEC公司财务数据（XBRL概念）",
        tool="sec_company_concept", endpoint="https://data.sec.gov/api/xbrl/companyconcept/",
        api_url="https://data.sec.gov/api/xbrl/companyconcept/", sort="", date_field="period", value_field="value",
        param_format="<CIK or ticker>/<us-gaap concept>",
        param_examples=("AAPL/RevenueFromContractWithCustomerExcludingAssessedTax",),
        param_pattern=r"[^/]*[^/\s][^/]*/[^/]*[^/\s][^/]*", tiebreak_field="filed", frequency="A",
        units="U.S. dollars", source_url="https://www.sec.gov/edgar/search/",
        notes=("Unavailable: the supplied handler drops period starts and filing provenance, so it yields no "
               "complete annual series. Use company filings via web research."),
        enabled=False),
    # EIA (needs EIA_API_KEY).  eia_query returns rows newest first; values arrive numeric.
    "eia/electricity_sales": _eia(
        "electricity/retail-sales", "sales", "M", title="EIA: Retail Sales of Electricity",
        title_zh="美国电力零售销售量", param_facets=("stateid", "sectorid"), param_format="<stateid>.<sectorid>",
        param_examples=("US.ALL", "US.COM", "US.IND", "US.RES", "VA.COM", "TX.COM", "CA.COM"),
        param_pattern=r"[A-Z]{2}\.(?:ALL|COM|IND|RES)", units_field="sales-units",
        native_units="million kilowatt hours", units="Million kilowatt-hours", source_url=_EIA_BROWSER,
        notes=("Electricity sold to ultimate customers (Forms EIA-861M/861); recent months are sample "
               "estimates replaced by the annual census. No data-center sector exists: commercial sales "
               "(COM), especially in VA and TX, are the usual data-center load proxy."),
        min_start="2001-01-01"),
    "eia/electricity_price": _eia(
        "electricity/retail-sales", "price", "M", title="EIA: Average Retail Price of Electricity",
        title_zh="美国电力平均零售价格", param_facets=("stateid", "sectorid"), param_format="<stateid>.<sectorid>",
        param_examples=("US.ALL", "US.COM", "US.IND", "US.RES"),
        param_pattern=r"[A-Z]{2}\.(?:ALL|COM|IND|RES)", units_field="price-units",
        native_units="cents per kilowatt-hour", units="Cents per kilowatt-hour", source_url=_EIA_BROWSER,
        notes="Revenue divided by sales (Form EIA-861M); nominal cents, not inflation-adjusted.",
        min_start="2001-01-01"),
    "eia/net_generation": _eia(
        "electricity/electric-power-operational-data", "generation", "M", title="EIA: Net Generation of Electricity",
        title_zh="美国发电量（按能源）", facets={"location": "US", "sectorid": "99"}, param_facets=("fueltypeid",),
        param_format="<fueltypeid>", param_examples=("ALL", "NG", "COW", "SUN", "WND", "NUC", "HYC"),
        param_pattern=r"ALL|NG|COW|SUN|WND|NUC|HYC", units_field="generation-units",
        native_units="thousand megawatthours", units="Thousand megawatt-hours", source_url=_EIA_BROWSER,
        notes=("All sectors, U.S. total (Form EIA-923). SUN is utility-scale solar (small-scale rooftop PV "
               "excluded); COW is all coal products; recent months are preliminary."),
        min_start="2001-01-01"),
    "eia/crude_production": _eia(
        "petroleum/crd/crpdn", "value", "M", title="EIA: U.S. Field Production of Crude Oil",
        title_zh="美国原油产量", facets={"series": "MCRFPUS2"}, units_field="units", native_units="MBBL/D",
        units="Thousand barrels per day",
        source_url="https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=MCRFPUS2&f=M",
        notes="EIA series MCRFPUS2 (monthly average per day); the latest months are estimates.",
        min_start="1920-01-01"),
    "eia/generating_capacity": _eia(
        "electricity/state-electricity-profiles/capability", "capability", "A",
        title="EIA: Net Summer Generating Capacity", title_zh="美国发电装机容量（夏季净容量）",
        facets={"stateId": "US", "producertypeid": "TOT"}, param_facets=("energysourceid",),
        param_format="<energysourceid>", param_examples=("ALL", "BAT", "SOL", "WND"),
        param_pattern=r"ALL|BAT|SOL|WND", units_field="capability-units", native_units="megawatts",
        units="Megawatts", source_url="https://www.eia.gov/electricity/state/",
        notes=("Year-end net summer capacity, all sectors (Form EIA-860; State Electricity Profiles table 4). "
               "BAT = utility-scale battery storage. Annual, published with about a one-year lag."),
        min_start="1990-01-01"),
    # BEA (needs BEA_API_KEY).  The tools drop units and cap observations per line, see notes.
    "bea/real_gdp_growth": _bea_nipa(
        "T10101", "Gross domestic product", "Percent change from preceding period (annual rate)",
        title="BEA NIPA Table 1.1.1: Real Gross Domestic Product, Percent Change", title_zh="美国实际GDP增长率（BEA）",
        notes=("Quarter-on-quarter change at an annual rate; advance, second and third estimates revise the "
               "latest quarter. Same series as fred:A191RL1Q225SBEA. The BEA tool returns at most 8 "
               "observations per line: request two years per call.")),
    "bea/real_pce_growth": _bea_nipa(
        "T10101", "Personal consumption expenditures", "Percent change from preceding period (annual rate)",
        title="BEA NIPA Table 1.1.1: Real Personal Consumption Expenditures, Percent Change",
        title_zh="美国实际个人消费支出增长率（BEA）",
        notes=("Same series as fred:DPCERL1Q225SBEA. The BEA tool returns at most 8 observations per line: "
               "request two years per call.")),
    "bea/personal_income": _bea_nipa(
        "T20100", "Personal income", "Millions of dollars (seasonally adjusted annual rate)",
        title="BEA NIPA Table 2.1: Personal Income", title_zh="美国个人收入（BEA，季度）",
        notes=("Quarterly level in millions (fred:PI is the monthly series in billions). The monthly table "
               "cannot be read completely through the BEA tool (8-observation cap).")),
    "bea/nominal_pce": _bea_nipa(
        "T10105", "Personal consumption expenditures", "Millions of dollars (seasonally adjusted annual rate)",
        title="BEA NIPA Table 1.1.5: Personal Consumption Expenditures", title_zh="美国个人消费支出（名义，BEA）",
        notes="Nominal quarterly level in millions of current dollars; two years per call (8-observation cap)."),
    "bea/value_added_by_industry": _recipe(
        kind="bea_industry", title="BEA GDP by Industry: Value Added", title_zh="美国分行业增加值（BEA）",
        tool="bea_gdp_by_industry", tool_args={"table_id": "1", "frequency": "Q"}, endpoint="GDPbyIndustry/1",
        api_url=f"{_BEA_API}?method=GetData&DataSetName=GDPbyIndustry&TableID=1&Frequency=Q", sort="",
        date_field="period", value_field="value", period_format="YYYYQroman", param_field="industry",
        param_format="<BEA industry code>", param_examples=("51", "514", "334", "22", "31G", "52"),
        param_pattern=r"[0-9][0-9A-Z]{1,5}", max_obs_per_call=5, frequency="Q", seasonal_adjustment="SAAR",
        units="Billions of dollars (seasonally adjusted annual rate)",
        source_url="https://www.bea.gov/itable/gdp-by-industry",
        notes=("Current-dollar value added (GDP by Industry table 1); exactly one industry row comes back. "
               "514 = data processing, internet publishing and other information services (closest BEA "
               "proxy for data centers and cloud). Quarters read 2025QI..2025QIV; the tool returns at most 5 "
               "observations per call, so request one year per call."),
        # Quarterly GDP by Industry starts in 2005; BEA rejects an earlier year ("Invalid year: 2004").
        min_start="2005-01-01", requires_key="BEA_API_KEY"),
}


_NO_DIMS: Mapping[str, str] = MappingProxyType({})


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
    # Verified native unit identity: (unit code, UNIT_MULT exponent) exactly as the provider rows
    # carry them (an absent UNIT_MULT reads 0, an absent UNIT_MEASURE ""); when set, the data
    # layer requires equality and shows ``units``, never the native label.
    native_unit: tuple[str, int] | None = None
    # Row attributes every returned row must carry (BIS UNIT_TYPE / CURRENCY / COLLECTION,
    # Data360 COMP_BREAKDOWN_1).  Read-only; excluded from equality and hashing.
    native_dims: Mapping[str, str] = field(default_factory=lambda: _NO_DIMS, compare=False)
    aggregation: str = ""    # native-daily -> monthly: "eop" (stocks, policy targets) | "avg" | ""
    status_policy: str = ""  # "" | "history_only" (WDI) | "weo_vintage" | "gep_vintage"
    fred_equivalent: str = ""  # FRED id carrying the same series (BLS quota / outage hint)
    preferred: str = ""      # faster equivalent catalog id; search and digest rank it first
    min_start: str = ""      # earliest valid start (YYYY-MM-DD); clamp before calling
    requires_key: str = ""   # env var the provider module needs (usgov EIA / BEA recipes)

    @property
    def provider(self) -> str:
        return self.series.split(":", 1)[0]

    @property
    def native(self) -> str:
        return self.series.split(":", 1)[1]


# ---------------------------------------------------------------------------
# Entry constructors (derive ids and citation pages from the provider patterns)
# ---------------------------------------------------------------------------

_CJK_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
               "八": 8, "九": 9}
# A Chinese numeral directly before a period or count word ("十年期", "两年", "三个月").
_CJK_NUMBER_RE = re.compile(r"[零〇一二两三四五六七八九十百]+(?=个?[年月季周期天倍])")


def _cjk_number(text: str) -> str:
    if "十" not in text and "百" not in text:
        return "".join(str(_CJK_DIGITS[ch]) for ch in text)
    total, current = 0, 0
    for ch in text:
        if ch in ("十", "百"):
            total += (current or 1) * (10 if ch == "十" else 100)
            current = 0
        else:
            current = _CJK_DIGITS[ch]
    return str(total + current)


def _cjk_numerals(text: str) -> str:
    """``"美国十年期国债"`` -> ``"美国10年期国债"`` (titles and keywords use Arabic digits)."""
    return _CJK_NUMBER_RE.sub(lambda match: _cjk_number(match.group(0)), text)


_CJK_RE = re.compile(r"[㐀-鿿]")
_WORD_RE = re.compile(r"[a-z0-9&]+")


def _stem(word: str) -> str:
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _entry(provider: str, native: str, title: str, title_zh: str, units: str, frequency: str,
           sa: str, geography: str, topics: tuple[str, ...], keywords: tuple[str, ...],
           notes: str, source_url: str, **policy: Any) -> CatalogEntry:
    cleaned: list[str] = []
    matched: set[str] = set()   # one score per matching form ("saving rate" == "savings rate")
    for keyword in keywords:
        norm = " ".join(_cjk_numerals(keyword).lower().split())
        form = norm if _CJK_RE.search(norm) else " ".join(_stem(word) for word in _WORD_RE.findall(norm))
        if norm and form not in matched:
            cleaned.append(norm)
            matched.add(form)
    if policy.get("native_dims"):
        policy["native_dims"] = MappingProxyType(dict(policy["native_dims"]))
    if policy.get("aggregation", "") not in AGGREGATIONS:
        raise ValueError(f"unknown aggregation for {provider}:{native}: {policy['aggregation']}")
    if policy.get("status_policy", "") not in STATUS_POLICIES:
        raise ValueError(f"unknown status policy for {provider}:{native}: {policy['status_policy']}")
    return CatalogEntry(series=f"{provider}:{native}", title=title, title_zh=title_zh, units=units,
                        frequency=frequency, seasonal_adjustment=sa, geography=geography,
                        topics=tuple(topics), keywords=tuple(cleaned), notes=notes,
                        source_url=source_url, **policy)


def _fred(sid: str, title: str, title_zh: str, units: str, frequency: str, sa: str,
          topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "",
          geography: str = "USA", aggregation: str = "") -> CatalogEntry:
    # Native-daily FRED series are prices, yields and rates (monthly mean) unless the entry
    # names "eop" (policy targets); stocks such as debt are usgov recipes.
    aggregation = aggregation or ("avg" if frequency == "D" else "")
    return _entry("fred", sid, title, title_zh, units, frequency, sa, geography, topics, keywords,
                  notes, f"https://fred.stlouisfed.org/series/{sid}", aggregation=aggregation)


# FRED ids carrying exactly the same BLS series (verified live 2026-10-12: same title, units and
# adjustment).  Keyless BLS allows 20 requests a day, so quota and outage hints name these.
# FRED has no series CUSR0000SAM; no mirror was verified for the remaining PPI, LAUS state,
# ECI, productivity and import/export price ids.
_BLS_FRED_EQUIVALENTS: dict[str, str] = {
    "CUUR0000SA0": "CPIAUCNS", "CUSR0000SA0": "CPIAUCSL", "CUUR0000SA0L1E": "CPILFENS",
    "CUSR0000SA0L1E": "CPILFESL", "CUSR0000SAH1": "CUSR0000SAH1", "CUSR0000SEHA": "CUSR0000SEHA",
    "CUSR0000SAF11": "CUSR0000SAF11", "CUSR0000SETA02": "CUSR0000SETA02", "CUSR0000SASLE": "CUSR0000SASLE",
    "CUUR0000SETB01": "CUUR0000SETB01", "CUUR0000SEHF01": "CUUR0000SEHF01", "APU000074714": "APU000074714",
    "APU000072610": "APU000072610", "APU0000708111": "APU0000708111", "APU0000703112": "APU0000703112",
    "WPSFD4": "PPIFIS", "LNS14000000": "UNRATE", "LNU04000000": "UNRATENSA", "LNS11300000": "CIVPART",
    "LNS12300060": "LNS12300060", "CES0000000001": "PAYEMS", "CES3000000001": "MANEMP",
    "CES0500000003": "CES0500000003", "CES0500000011": "CES0500000011", "CES0500000002": "AWHAETP",
    "JTS000000000000000JOL": "JTSJOL", "JTS000000000000000QUR": "JTSQUR", "JTS000000000000000HIR": "JTSHIR",
    "JTS000000000000000LDR": "JTSLDR",
}


def _bls(sid: str, title: str, title_zh: str, units: str, frequency: str, sa: str,
         topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "") -> CatalogEntry:
    mirror = _BLS_FRED_EQUIVALENTS.get(sid, "")
    return _entry("bls", sid, title, title_zh, units, frequency, sa, "USA", topics, keywords,
                  notes, f"https://data.bls.gov/timeseries/{sid}", fred_equivalent=f"fred:{mirror}" if mirror else "")


# Verified native unit identity per BIS flow (live capture of every catalog key, 2026-10-12):
# (UNIT_MEASURE code, UNIT_MULT) plus the key dimensions whose codes carry the denominator or
# currency.  WS_TC rows say only "Per cent" (367); the GDP denominator is UNIT_TYPE 770.
# WS_XRU rows carry no UNIT_MEASURE and WS_EER rows no UNIT_MULT.
_BIS_UNIT_PINS: dict[str, tuple[tuple[str, int], tuple[str, ...]]] = {
    "WS_CBPOL": (("368", 0), ()),
    "WS_CREDIT_GAP": (("770", 0), ()),
    "WS_TC": (("367", 0), ("UNIT_TYPE",)),
    "WS_DSR": (("367", 0), ()),
    "WS_SPP": (("628", 0), ()),
    "WS_XRU": (("", 0), ("CURRENCY", "COLLECTION")),
    "WS_EER": (("882", 0), ()),
    "WS_LONG_CPI": (("771", 0), ()),
    "WS_CBTA": (("XDC", 9), ("CURRENCY",)),
    "WS_GLI": (("USD", 6), ()),
}


def _bis(flow: str, key: str, title: str, title_zh: str, units: str, geography: str,
         topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "") -> CatalogEntry:
    meta = BIS_FLOWS[flow]
    url = f"https://data.bis.org/topics/{meta['topic']}/BIS,{flow},{meta['version']}/{key}"
    native_unit, pinned = _BIS_UNIT_PINS[flow]
    parts = dict(zip(meta["dims"], key.split(".")))
    return _entry("bis", f"{flow}/{key}", title, title_zh, units, key.split(".", 1)[0], "",
                  geography, topics, keywords, notes, url, native_unit=native_unit,
                  native_dims={dim: parts[dim] for dim in pinned})


def _imf(flow: str, key: str, title: str, title_zh: str, units: str, geography: str,
         topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "",
         preferred: str = "") -> CatalogEntry:
    meta = IMF_FLOWS[flow]
    url = f"https://data.imf.org/en/datasets/{meta['agency']}:{meta['base_flow']}"
    return _entry("imf", f"{flow}/{key}", title, title_zh, units, key.rsplit(".", 1)[1], "",
                  geography, topics, keywords, notes, url, preferred=preferred,
                  status_policy="weo_vintage" if meta["base_flow"] == "WEO" else "")


# Data360 status policy per database: WDI publishes history only; WEO and GEP mix history
# with publisher projections and their rows carry no status (vintage rules in the data layer).
_WB_STATUS_POLICIES: dict[str, str] = {"WB_WDI": "history_only", "IMF_WEO": "weo_vintage", "WB_GEP": "gep_vintage"}
# IMF WEO rows on Data360 carry COMP_BREAKDOWN_1="V_LST" (latest published vintage) on every row.
_WB_DIM_PINS: dict[str, dict[str, str]] = {"IMF_WEO": {"COMP_BREAKDOWN_1": "V_LST"}}


def _wb(indicator: str, iso3: str, title: str, title_zh: str, units: str,
        topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "", *,
        native_unit: tuple[str, int]) -> CatalogEntry:
    database = wb_database(indicator)
    if database is None:
        raise ValueError(f"unsupported Data360 database for wb:{indicator}")
    return _entry("wb", f"{indicator}/{iso3}", title, title_zh, units, "A", "", iso3, topics, keywords,
                  notes, f"https://data360.worldbank.org/en/indicator/{indicator}", native_unit=native_unit,
                  native_dims=_WB_DIM_PINS.get(database, {}), status_policy=_WB_STATUS_POLICIES[database])


def _usgov(recipe_id: str, topics: tuple[str, ...], keywords: tuple[str, ...],
           title_suffix: str = "", title_zh: str = "", notes: str = "",
           geography: str = "USA", preferred: str = "") -> CatalogEntry:
    resolved = resolve_usgov_recipe(recipe_id)
    if resolved is None or not resolved[1]["enabled"]:
        raise ValueError(f"unknown or disabled usgov recipe id: {recipe_id}")
    _key, recipe, _param = resolved
    title = recipe["title"] + (f": {title_suffix}" if title_suffix else "")
    return _entry("usgov", recipe_id, title, title_zh or recipe["title_zh"], recipe["units"],
                  recipe["frequency"], recipe["seasonal_adjustment"], geography, topics, keywords,
                  notes or recipe["notes"], recipe["source_url"], aggregation=recipe["aggregation"],
                  min_start=recipe["min_start"], requires_key=recipe["requires_key"], preferred=preferred)


def resolve_usgov_recipe(native: str) -> tuple[str, dict[str, Any], str] | None:
    """``"treasury/fx/Japan-Yen"`` -> ``("treasury/fx", recipe, "Japan-Yen")``.

    Recipe keys match case-insensitively; the parameter keeps its case (Treasury
    filters and EIA facets are case-sensitive).  Returns None for an unknown recipe,
    a missing parameter, a parameter given to a recipe that takes none, or a
    parameter outside the recipe's ``param_pattern``.
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
            if recipe["param_pattern"] and not re.fullmatch(recipe["param_pattern"], param):
                return None
            return key, recipe, param
    return None


def _env_value(env: Mapping[str, str] | None, key: str) -> str:
    source = os.environ if env is None else env
    return str(source.get(key) or "").strip()


def recipe_available(recipe: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> bool:
    """True when the supplied usgov handler can serve ``recipe`` here: the recipe is
    enabled and the key its module needs (``requires_key``) is set in ``env``
    (default ``os.environ``)."""
    if not recipe.get("enabled", True):
        return False
    key = str(recipe.get("requires_key") or "")
    return not key or bool(_env_value(env, key))


def entry_available(entry: CatalogEntry, *, env: Mapping[str, str] | None = None) -> bool:
    """True unless the entry needs a provider key that ``env`` (default ``os.environ``) lacks."""
    return not entry.requires_key or bool(_env_value(env, entry.requires_key))


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
    _fred("DPCERL1Q225SBEA", "Real Personal Consumption Expenditures", "美国实际个人消费支出增长率（环比折年率）",
          "Percent Change from Preceding Period", "Q", "SAAR", ("consumption", "growth"),
          ("real consumption growth", "consumer spending growth", "pce growth", "消费增长", "居民消费增长"),
          "Quarter-on-quarter change at an annual rate (NIPA Table 1.1.1 line 2)."),
    _fred("DSPIC96", "Real Disposable Personal Income", "美国实际个人可支配收入",
          "Billions of Chained 2017 Dollars", "M", "SAAR", ("income",),
          ("disposable income", "household income", "real income", "可支配收入", "居民收入")),
    _fred("PSAVERT", "Personal Saving Rate", "美国个人储蓄率", "Percent", "M", "SAAR", ("income",),
          ("saving rate", "savings rate", "household saving", "储蓄率")),
    _fred("TOTALSA", "Total Vehicle Sales", "美国汽车总销量", "Millions of Units", "M", "SAAR",
          ("consumption", "autos"), ("vehicle sales", "car sales", "auto sales", "light vehicle sales", "汽车销量")),
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
           "美联储资产负债表", "缩表", "量化宽松"),
          "Wednesday level (a stock); weekly data are not averaged.", aggregation="eop"),
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
           "通胀", "通货膨胀", "整体通胀", "消费者价格指数", "物价"),
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
          "Step series that changes only at FOMC decisions; the lower limit is fred:DFEDTARL.", aggregation="eop"),
    _fred("DFEDTARL", "Federal Funds Target Range - Lower Limit", "联邦基金目标利率区间下限", "Percent", "D",
          "NSA", ("rates", "policy"),
          ("target range lower limit", "fed target rate", "fomc decision", "目标利率下限"),
          "Step series that changes only at FOMC decisions; the upper limit is fred:DFEDTARU.", aggregation="eop"),
    _fred("ECBDFR", "ECB Deposit Facility Rate for Euro Area", "欧洲央行存款便利利率", "Percent", "D", "NSA",
          ("rates", "policy"),
          ("deposit facility rate", "deposit facility", "ecb deposit rate", "deposit rate", "ecb policy rate",
           "ecb rate", "ecb interest rate", "european central bank", "policy rate", "interest rate", "rate cut",
           "rate hike", "存款便利利率", "存款便利", "存款利率", "欧洲央行利率", "欧央行利率", "政策利率", "降息",
           "加息"),
          "The rate through which the ECB steers its policy stance; step series that changes only at Governing "
          "Council decisions. bis:WS_CBPOL/M.XM carries it from 18 Sep 2024 only (main refinancing rate before).",
          geography="EMU", aggregation="eop"),
    _fred("SOFR", "Secured Overnight Financing Rate", "有担保隔夜融资利率", "Percent", "D", "NSA", ("rates",),
          ("sofr", "overnight rate", "repo rate", "隔夜融资利率")),
    _fred("DGS3MO",
          "Market Yield on U.S. Treasury Securities at 3-Month Constant Maturity, Quoted on an Investment Basis",
          "美国3个月期国债收益率", "Percent", "D", "NSA", ("rates",),
          ("3-month treasury", "t-bill yield", "short-term rate", "3个月国债收益率", "短期国债")),
    _fred("DGS2",
          "Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity, Quoted on an Investment Basis",
          "美国2年期国债收益率", "Percent", "D", "NSA", ("rates",),
          ("2-year treasury", "2-year yield", "two-year yield", "2年期国债收益率", "两年期国债", "两年期美债")),
    _fred("DGS10",
          "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis",
          "美国10年期国债收益率", "Percent", "D", "NSA", ("rates",),
          ("10-year treasury", "10-year yield", "ten-year yield", "treasury yield", "bond yield",
           "long-term rate", "10年期国债收益率", "十年期国债", "十年期美债", "美债收益率", "长期利率")),
    _fred("DGS30",
          "Market Yield on U.S. Treasury Securities at 30-Year Constant Maturity, Quoted on an Investment Basis",
          "美国30年期国债收益率", "Percent", "D", "NSA", ("rates",),
          ("30-year treasury", "long bond", "30-year yield", "30年期国债收益率", "三十年期国债")),
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
    # Semiconductors and electronics (AI and data-center supply chain)
    _fred("IPG3344S", "Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic "
          "Component (NAICS = 3344)", "美国半导体及其他电子元件工业生产指数", "Index 2017=100", "M", "SA",
          ("technology", "production"),
          ("semiconductor", "semiconductors", "chips", "semiconductor production", "semiconductor output",
           "chip production", "chip output", "半导体", "芯片", "集成电路", "半导体生产", "芯片产量"),
          "Real output index for NAICS 3344 (chips and other electronic components)."),
    _fred("CAPUTLG3344S", "Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic "
          "Component (NAICS = 3344)", "美国半导体及其他电子元件产能利用率", "Percent", "M", "SA",
          ("technology", "production"),
          ("semiconductor capacity utilization", "chip capacity utilization", "fab utilization",
           "半导体产能利用率", "芯片产能")),
    _fred("IPG334S", "Industrial Production: Manufacturing: Durable Goods: Computer and Electronic Product "
          "(NAICS = 334)", "美国计算机和电子产品工业生产指数", "Index 2017=100", "M", "SA", ("technology", "production"),
          ("computer production", "electronics production", "electronics output", "computer and electronic products",
           "计算机和电子产品", "电子产品生产")),
    _fred("A34SNO", "Manufacturers' New Orders: Computers and Electronic Products", "美国计算机和电子产品新订单",
          "Millions of Dollars", "M", "SA", ("technology", "production"),
          ("electronics orders", "computer orders", "semiconductor demand", "电子产品订单", "计算机订单"),
          "Census M3 survey; nominal dollars."),
    _fred("A34SVS", "Manufacturers' Value of Shipments: Computers and Electronic Products", "美国计算机和电子产品出货值",
          "Millions of Dollars", "M", "SA", ("technology", "production"),
          ("electronics shipments", "computer shipments", "semiconductor shipments", "chip shipments",
           "电子产品出货", "芯片出货"),
          "Census M3 survey; nominal dollars for all computer and electronic products, not chips alone."),
    _fred("PCU33443344", "Producer Price Index by Industry: Semiconductor and Other Electronic Component "
          "Manufacturing", "美国半导体及其他电子元件制造业生产者价格指数", "Index Dec 1984=100", "M", "NSA",
          ("technology", "inflation"),
          ("semiconductor prices", "chip prices", "semiconductor ppi", "半导体价格", "芯片价格"),
          "Quality-adjusted prices drift down over time; compare changes, not levels."),
    _fred("NASDAQSOX", "PHLX Semiconductor", "费城半导体指数", "Index", "D", "NSA", ("technology", "markets"),
          ("philadelphia semiconductor index", "sox", "semiconductor stocks", "chip stocks", "费城半导体指数",
           "半导体股", "芯片股"),
          "Price index without dividends."),
    # Trade and fiscal
    _fred("BOPGSTB", "Trade Balance: Goods and Services, Balance of Payments Basis", "美国商品和服务贸易差额",
          "Millions of Dollars", "M", "SA", ("trade",),
          ("trade balance", "trade deficit", "net exports", "贸易逆差", "贸易差额", "贸易平衡"),
          "Negative values are deficits."),
    _fred("EXPGSC1", "Real Exports of Goods and Services", "美国实际商品和服务出口",
          "Billions of Chained 2017 Dollars", "Q", "SAAR", ("trade",), ("real exports", "exports", "出口")),
    _fred("IMPGSC1", "Real imports of goods and services", "美国实际商品和服务进口",
          "Billions of Chained 2017 Dollars", "Q", "SAAR", ("trade",), ("real imports", "imports", "进口")),
    _fred("IMPCH", "U.S. Imports of Goods by Customs Basis from China", "美国自中国商品进口额（海关口径）",
          "Millions of Dollars", "M", "NSA", ("trade",),
          ("imports from china", "us-china trade", "chinese imports", "china tariffs", "tariffs on china",
           "自中国进口", "中美贸易", "对华关税"),
          "Census customs basis, not seasonally adjusted: compare with the same month a year earlier.",
          geography="CHN"),
    _fred("EXPCH", "U.S. Exports of Goods by F.A.S. Basis to Mainland China", "美国对中国大陆商品出口额",
          "Millions of Dollars", "M", "NSA", ("trade",),
          ("exports to china", "us-china trade", "对华出口", "中美贸易"),
          "Census F.A.S. basis, not seasonally adjusted.", geography="CHN"),
    _fred("B235RC1Q027SBEA", "Federal government current tax receipts: Taxes on production and imports: Customs "
          "duties", "美国联邦关税收入（国民账户，折年率）", "Billions of Dollars", "Q", "SAAR", ("trade", "fiscal"),
          ("customs duties", "tariff revenue", "tariff receipts", "import duties", "关税收入"),
          "NIPA accrual basis at an annual rate; the monthly cash series is usgov:treasury/mts_customs_duties."),
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
         ("cpi", "headline cpi", "headline inflation", "official inflation", "cpi-u", "inflation", "consumer prices",
          "消费者价格指数", "通胀", "整体通胀", "cpi同比"),
         "Index level; the published 12-month inflation rate is the yoy change of this NSA series."),
    _bls("CUSR0000SA0", "All items in U.S. city average, all urban consumers, seasonally adjusted",
         "美国CPI-U全部项目（季调）", _CPI_UNITS, "M", "SA", ("inflation",),
         ("cpi", "headline inflation", "monthly inflation", "cpi month over month", "整体通胀", "cpi环比"),
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
         "美国CPI二手车", _CPI_UNITS, "M", "SA", ("inflation", "autos"),
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
    "US": ("USA", "United States", "美国", ("federal reserve", "fed", "fomc", "federal funds target range", "美联储")),
    "XM": ("EMU", "Euro area", "欧元区", ("ecb", "european central bank", "deposit facility rate", "欧洲央行",
                                        "存款便利利率")),
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


# What BIS reports as the policy rate where it is not the obvious one (BIS COMPILATION attribute).
_CBPOL_NOTES: dict[str, str] = {
    "US": "For the United States BIS reports the midpoint of the federal funds target range; "
          "fred:DFEDTARU is the upper limit.",
    "XM": "From 18 Sep 2024 BIS reports the ECB deposit facility rate (daily: fred:ECBDFR); before that, the main "
          "refinancing operations rate.",
}


def _cbpol(area: str) -> CatalogEntry:
    iso3, name, name_zh, extra = _BIS_AREAS[area]
    notes = _CBPOL_NOTES.get(area, "")
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
             ("inflation", "cpi", "consumer prices", "headline inflation", "通胀", "整体通胀", "cpi同比")),
        _bis("WS_LONG_CPI", "M.CN.771", "Consumer prices: China - Year-on-year changes, in per cent",
             "中国CPI同比（BIS）", "Per cent, year-on-year change", "CHN", ("inflation",),
             ("inflation", "cpi", "consumer prices", "headline inflation", "deflation", "通胀", "整体通胀", "通缩",
              "cpi同比")),
        _bis("WS_LONG_CPI", "M.XM.771", "Consumer prices: Euro area - Year-on-year changes, in per cent",
             "欧元区CPI同比（BIS）", "Per cent, year-on-year change", "EMU", ("inflation",),
             ("inflation", "hicp", "consumer prices", "headline inflation", "通胀", "整体通胀"),
             "Euro-area HICP as compiled by the BIS."),
        _bis("WS_LONG_CPI", "M.JP.771", "Consumer prices: Japan - Year-on-year changes, in per cent",
             "日本CPI同比（BIS）", "Per cent, year-on-year change", "JPN", ("inflation",),
             ("inflation", "cpi", "consumer prices", "headline inflation", "通胀", "整体通胀")),
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
          keywords: tuple[str, ...], notes: str = _PCPS_NOTE, transformation: str = "USD",
          preferred: str = "") -> CatalogEntry:
    return _imf("PCPS", f"G001.{code}.{transformation}.M", title, title_zh, units, "WLD", topics, keywords, notes,
                preferred=preferred)


def _imf_cpi(iso3: str, name: str, name_zh: str, extra: tuple[str, ...] = ()) -> CatalogEntry:
    return _imf("CPI", f"{iso3}.CPI._T.YOY_PCH_PA_PT.M",
                f"Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: {name}",
                f"{name_zh}CPI同比（IMF）", "Percent change, year over year", iso3, ("inflation",),
                ("inflation", "cpi", "consumer prices", "headline inflation", "通胀", "整体通胀", "cpi同比") + extra,
                "IMF CPI dataset; the latest month lags national releases by one to two months.")


_IMF_ENTRIES: tuple[CatalogEntry, ...] = (
    # WEO aggregates (Data360 carries WEO countries only)
    _imf("WEO", "G001.NGDP_RPCH.A", "Gross domestic product (GDP), Constant prices, Percent change: World",
         "世界实际GDP增长率（IMF WEO）", "Percent change", "WLD", ("growth", "projections"),
         ("world gdp growth", "global gdp growth", "global growth", "global gdp", "world economy", "全球经济增长",
          "世界经济增长", "全球gdp增长"), _WEO_NOTE),
    _imf("WEO", "G163.NGDP_RPCH.A", "Gross domestic product (GDP), Constant prices, Percent change: Euro Area (EA)",
         "欧元区实际GDP增长率（IMF WEO）", "Percent change", "EMU", ("growth", "projections"),
         ("euro area gdp growth", "eurozone growth", "gdp growth", "economic growth", "欧元区经济增长", "gdp增长"),
         _WEO_NOTE),
    _imf("WEO", "USA.NGDP_RPCH.A", "Gross domestic product (GDP), Constant prices, Percent change: United States",
         "美国实际GDP增长率（IMF WEO）", "Percent change", "USA", ("growth", "projections"),
         ("gdp growth", "imf forecast", "economic growth", "gdp增长", "imf预测"),
         _WEO_NOTE + " Same values as wb:IMF_WEO_NGDP_RPCH/USA, which is faster.",
         preferred="wb:IMF_WEO_NGDP_RPCH/USA"),
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
          _PCPS_NOTE + " Netherlands TTF day-ahead; fred:PNGASEUUSDM mirrors it (faster; it can lag the IMF release).",
          preferred="fred:PNGASEUUSDM"),
    _pcps("PNGASJP", "LNG, Asia, US dollars per million metric British thermal units of gas, Unit prices",
          "亚洲液化天然气价格（IMF月均）", "U.S. dollars per million British thermal units", ("energy", "commodities"),
          ("lng price", "asian lng", "liquefied natural gas", "液化天然气价格", "lng")),
    _pcps("PCOALAU", "Coal, Australia, US dollars per metric tonne, Unit prices", "澳大利亚动力煤价格（IMF月均）",
          "U.S. dollars per metric ton", ("energy", "commodities"),
          ("coal price", "thermal coal", "newcastle coal", "煤价", "动力煤")),
    _pcps("PURAN", "Uranium, US dollars per pound, Unit prices", "铀价格（IMF月均）", "U.S. dollars per pound",
          ("energy", "commodities"), ("uranium price", "uranium", "nuclear fuel", "铀价")),
    _pcps("PCOPP", "Copper, US dollars per metric tonne, Unit prices", "铜价格（IMF月均）", "U.S. dollars per metric ton",
          ("commodities",), ("copper price", "copper", "lme copper", "铜价", "铜"),
          _PCPS_NOTE + " fred:PCOPPUSDM mirrors it (faster; it can lag the IMF release).", preferred="fred:PCOPPUSDM"),
    _pcps("PALUM", "Aluminum, US dollars per metric tonne, Unit prices", "铝价格（IMF月均）", "U.S. dollars per metric ton",
          ("commodities",), ("aluminum price", "aluminium", "aluminum", "铝价")),
    _pcps("PNICK", "Nickel, US dollars per metric tonne, Unit prices", "镍价格（IMF月均）", "U.S. dollars per metric ton",
          ("commodities", "autos"), ("nickel price", "nickel", "battery metals", "镍价")),
    _pcps("PCOBA", "Cobalt, US dollars per pound, Unit prices", "钴价格（IMF月均）", "U.S. dollars per metric ton",
          ("commodities", "autos"), ("cobalt price", "cobalt", "battery metals", "钴价"),
          "IMF label says per pound, but the series description (LME spot, USD/ton) and the magnitude are "
          "US dollars per metric ton."),
    _pcps("PLITH", "Lithium, 99%, Battery Grade, Unit prices", "锂价格（电池级，IMF月均）",
          "U.S. dollars (IMF states no unit)", ("commodities", "energy", "autos"),
          ("lithium price", "lithium", "battery metals", "ev batteries", "battery storage costs", "锂价", "碳酸锂",
           "电池金属", "动力电池"),
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
# World Bank Data360 (WDI history, IMF WEO country projections, WB GEP).  native_unit pins the
# (UNIT_MEASURE, UNIT_MULT) every row carried in the live capture of 2026-10-12; the Data360
# metadata unit is free text ("%", "Unit", "current US$") and is never compared.
# ---------------------------------------------------------------------------

_WB_AREAS: dict[str, tuple[str, str]] = {
    "USA": ("United States", "美国"), "CHN": ("China", "中国"), "JPN": ("Japan", "日本"),
    "DEU": ("Germany", "德国"), "GBR": ("United Kingdom", "英国"), "IND": ("India", "印度"),
    "EMU": ("Euro area", "欧元区"), "WLD": ("World", "世界"),
}
_WB_WEO_NOTE = ("IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF "
                "projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163.")


def _wb_series(indicator: str, iso3: str, title: str, title_zh: str, units: str,
               topics: tuple[str, ...], keywords: tuple[str, ...], notes: str = "", *,
               native_unit: tuple[str, int]) -> CatalogEntry:
    name, name_zh = _WB_AREAS[iso3]
    return _wb(indicator, iso3, f"{title}: {name}", f"{name_zh}{title_zh}", units, topics, keywords, notes,
               native_unit=native_unit)


_WEO_GROWTH_KW = ("gdp growth", "economic growth", "real gdp growth", "growth forecast", "imf forecast",
                  "gdp增长", "实际gdp增长", "实际gdp增速", "经济增长", "增长率", "增速")
_WEO_CPI_KW = ("inflation", "cpi", "headline inflation", "inflation forecast", "imf forecast", "通胀", "通货膨胀",
               "整体通胀", "cpi通胀")
_WEO_LUR_KW = ("unemployment", "unemployment rate", "jobless rate", "失业率", "失业")
_WEO_DEBT_KW = ("government debt", "public debt", "debt to gdp", "sovereign debt", "政府债务", "债务占gdp", "国债")
_WEO_CA_KW = ("current account", "external balance", "trade surplus", "经常账户", "经常项目")

_WB_ENTRIES: tuple[CatalogEntry, ...] = (
    tuple(_wb_series("IMF_WEO_NGDP_RPCH", iso3, "Gross domestic product (GDP), Constant prices, Percent change",
                     "实际GDP增长率（IMF WEO）", "Percent change", ("growth", "projections"), _WEO_GROWTH_KW,
                     _WB_WEO_NOTE,
                       native_unit=("PC", 0))
          for iso3 in ("USA", "CHN", "JPN", "DEU", "GBR", "IND"))
    + tuple(_wb_series("IMF_WEO_PCPIPCH", iso3, "All Items, Consumer price index (CPI), Period average, percent change",
                       "CPI通胀率（IMF WEO）", "Percent change", ("inflation", "projections"), _WEO_CPI_KW,
                       _WB_WEO_NOTE,
                       native_unit=("PC", 0))
            for iso3 in ("USA", "CHN", "JPN", "DEU", "GBR", "IND"))
    + tuple(_wb_series("IMF_WEO_LUR", iso3, "Unemployment rate", "失业率（IMF WEO）", "Percent of labor force",
                       ("labor", "projections"), _WEO_LUR_KW,
                       _WB_WEO_NOTE + " Data360 labels the unit 'Percentage of population'; WEO defines it as "
                       "percent of the labor force.",
                       native_unit=("PT_POP", 0))
            for iso3 in ("USA", "CHN", "JPN", "DEU", "GBR"))
    + tuple(_wb_series("IMF_WEO_GGXWDG_NGDP", iso3, "Gross debt, General government, Percent of GDP",
                       "政府总债务占GDP比率（IMF WEO）", "Percent of GDP", ("fiscal", "projections"), _WEO_DEBT_KW,
                       _WB_WEO_NOTE,
                       native_unit=("PT_GDP", 0))
            for iso3 in ("USA", "CHN", "JPN", "GBR"))
    + tuple(_wb_series("IMF_WEO_BCA_NGDPD", iso3, "Current account balance (credit less debit), Percent of GDP",
                       "经常账户余额占GDP比率（IMF WEO）", "Percent of GDP", ("trade", "projections"), _WEO_CA_KW,
                       _WB_WEO_NOTE,
                       native_unit=("PT_GDP", 0))
            for iso3 in ("USA", "CHN", "DEU", "JPN"))
    + tuple(_wb_series("IMF_WEO_NGDPD", iso3, "Gross domestic product (GDP), Current prices, US dollar",
                       "名义GDP（美元，IMF WEO）", "U.S. dollars", ("growth", "projections"),
                       ("nominal gdp", "gdp in dollars", "economy size", "gdp size", "名义gdp", "经济总量", "gdp规模"),
                       _WB_WEO_NOTE + " Values are whole U.S. dollars although the rows carry UNIT_MULT 9 and the "
                       "metadata unit reads 'US dollars (Billions)'; divide by 1e9 for billions.",
                       native_unit=("USD", 9))
            for iso3 in ("USA", "CHN"))
    + tuple(_wb_series("WB_GEP_NYGDPMKTPKDZ", iso3,
                       "GDP growth, constant (average 2010-19 prices and market exchange rates)",
                       "GDP增长率（世界银行全球经济展望）", "Percent change per annum", ("growth", "projections"),
                       ("gdp growth", "real gdp growth", "growth forecast", "world bank forecast",
                        "global economic prospects", "gdp增长", "gdp增速", "实际gdp增长", "实际gdp增速", "经济增速",
                        "世界银行预测"),
                       "World Bank Global Economic Prospects: short window (about five years) whose final years "
                       "are World Bank forecasts. No world aggregate in Data360.",
                       native_unit=("PC_A", 0))
            for iso3 in ("USA", "CHN", "IND", "EMU"))
    + tuple(_wb_series("WB_WDI_NY_GDP_MKTP_KD_ZG", iso3, "GDP (annual % growth)", "GDP年增长率（世界发展指标）",
                       "Percent change per annum", ("growth",),
                       ("gdp growth", "real gdp growth", "economic growth", "annual gdp growth", "gdp增长", "gdp增速",
                        "实际gdp增长", "实际gdp增速", "经济增长", "经济增速"),
                       "World Development Indicators history (actuals only); latest year lags one to two years.",
                       native_unit=("PC_A", 0))
            for iso3 in ("USA", "CHN", "IND", "WLD"))
    + tuple(_wb_series("WB_WDI_SP_POP_TOTL", iso3, "Population, total", "总人口（世界发展指标）", "Persons",
                       ("population",), ("population", "demographics", "people", "人口", "总人口"),
                       "Mid-year estimates; latest year lags one to two years.",
                       native_unit=("PS", 0))
            for iso3 in ("USA", "CHN", "IND", "WLD"))
    + tuple(_wb_series("WB_WDI_NY_GDP_PCAP_CD", iso3, "GDP per capita (current US$)", "人均GDP（现价美元）",
                       "Current U.S. dollars", ("growth", "income"),
                       ("gdp per capita", "income per person", "living standards", "人均gdp", "人均收入"),
                       native_unit=("USD", 0))
            for iso3 in ("USA", "CHN", "IND"))
    + tuple(_wb_series("WB_WDI_EN_GHG_CO2_MT_CE_AR5", iso3,
                       "Carbon dioxide (CO2) emissions (total) excluding LULUCF (Mt CO2e)",
                       "二氧化碳排放总量（不含土地利用）", "Mt CO2 equivalent", ("climate", "energy"),
                       ("co2 emissions", "carbon emissions", "emissions", "greenhouse gas", "二氧化碳排放", "碳排放"),
                       "EDGAR-based estimates; latest year lags one to two years.",
                       native_unit=("MTCO2E", 0))
            for iso3 in ("WLD", "CHN", "USA", "IND"))
    + tuple(_wb_series("WB_WDI_EG_USE_ELEC_KH_PC", iso3, "Electric power consumption (kWh per capita)",
                       "人均用电量", "Kilowatt-hours per capita", ("energy",),
                       ("electricity consumption", "power consumption", "electricity demand", "用电量", "电力消费",
                        "电力需求", "用电需求"),
                       "Latest year lags one to two years.", native_unit=("KWH", 0))
            for iso3 in ("CHN", "USA", "IND"))
    + (
        _wb_series("WB_WDI_FP_CPI_TOTL_ZG", "CHN", "Inflation, consumer prices (annual % growth)",
                   "CPI年通胀率（世界发展指标）", "Percent change per annum", ("inflation",),
                   ("inflation", "annual inflation", "consumer prices", "headline inflation", "通胀", "整体通胀", "通缩"),
                   native_unit=("PC_A", 0)),
        _wb_series("WB_WDI_FP_CPI_TOTL_ZG", "IND", "Inflation, consumer prices (annual % growth)",
                   "CPI年通胀率（世界发展指标）", "Percent change per annum", ("inflation",),
                   ("inflation", "annual inflation", "consumer prices", "headline inflation", "通胀", "整体通胀"),
                   native_unit=("PC_A", 0)),
        _wb_series("WB_WDI_NE_TRD_GNFS_ZS", "CHN", "Trade (% of GDP)", "贸易占GDP比重", "Percent of GDP", ("trade",),
                   ("trade openness", "trade to gdp", "贸易依存度", "贸易占gdp"), native_unit=("PT_GDP", 0)),
        _wb_series("WB_WDI_NE_EXP_GNFS_ZS", "CHN", "Exports of goods and services (% of GDP)", "出口占GDP比重",
                   "Percent of GDP", ("trade",), ("exports to gdp", "export dependence", "出口依存度", "出口占gdp"),
                   native_unit=("PT_GDP", 0)),
        _wb_series("WB_WDI_SL_UEM_TOTL_ZS", "CHN", "Unemployment, total (% of total labor force) (modeled ILO estimate)",
                   "失业率（国际劳工组织模型估计）", "Percent of total labor force", ("labor",),
                   ("unemployment", "unemployment rate", "失业率"),
                   "Modeled ILO estimate; differs from China's surveyed urban unemployment rate.",
                   native_unit=("PT_LF", 0)),
    )
)


# ---------------------------------------------------------------------------
# usgov (Treasury Fiscal Data, USAspending, EIA, BEA) -- recipes above
# ---------------------------------------------------------------------------

_DEBT_KW = ("national debt", "federal debt", "public debt", "debt ceiling", "us debt", "国债", "美国债务", "债务上限")
_MTS_KW = ("federal budget", "monthly treasury statement", "mts", "财政收支")
_ELEC_KW = ("electricity demand", "power demand", "electricity consumption", "electricity sales", "电力需求",
            "用电需求", "用电量", "售电量")
_DATA_CENTER_KW = ("data center electricity", "data center power", "data center demand", "数据中心用电")

_USGOV_ENTRIES: tuple[CatalogEntry, ...] = (
    _usgov("treasury/debt_to_penny", ("fiscal",), _DEBT_KW + ("debt to the penny", "total public debt", "联邦债务")),
    _usgov("treasury/debt_held_public", ("fiscal",), _DEBT_KW + ("debt held by the public", "marketable debt", "公众持有债务")),
    _usgov("treasury/mts_deficit", ("fiscal",),
           _MTS_KW + ("budget deficit", "monthly deficit", "fiscal deficit", "deficit", "财政赤字", "赤字")),
    _usgov("treasury/mts_receipts", ("fiscal",),
           _MTS_KW + ("federal receipts", "tax revenue", "government revenue", "tax receipts", "财政收入", "税收")),
    _usgov("treasury/mts_outlays", ("fiscal",),
           _MTS_KW + ("federal outlays", "government spending", "federal spending", "财政支出", "政府支出")),
    _usgov("treasury/mts_customs_duties", ("fiscal", "trade"),
           _MTS_KW + ("customs duties", "tariff revenue", "tariff receipts", "tariffs collected", "import duties",
                      "关税收入", "关税", "海关关税")),
    _usgov("treasury/mts_individual_income_taxes", ("fiscal", "income"),
           _MTS_KW + ("individual income taxes", "income tax receipts", "personal income tax", "个人所得税")),
    _usgov("treasury/mts_corporation_income_taxes", ("fiscal",),
           _MTS_KW + ("corporation income taxes", "corporate income taxes", "corporate tax receipts", "企业所得税",
                      "公司所得税")),
    _usgov("treasury/mts_interest_gross", ("fiscal", "rates"),
           _MTS_KW + ("interest on the debt", "interest outlays", "debt interest payments", "interest expense",
                      "国债利息", "利息支出")),
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
    # EIA (advertised only with EIA_API_KEY)
    _usgov("eia/electricity_sales/US.ALL", ("energy",),
           _ELEC_KW + ("retail electricity sales", "total electricity sales", "全社会用电量"),
           title_suffix="U.S. total, all sectors", title_zh="美国电力零售销售量（全部部门）"),
    _usgov("eia/electricity_sales/US.COM", ("energy", "technology"),
           _ELEC_KW + _DATA_CENTER_KW + ("commercial electricity sales", "commercial electricity", "商业用电"),
           title_suffix="U.S. total, commercial sector", title_zh="美国商业部门电力销售量"),
    _usgov("eia/electricity_sales/US.IND", ("energy", "production"),
           _ELEC_KW + ("industrial electricity sales", "industrial electricity", "工业用电"),
           title_suffix="U.S. total, industrial sector", title_zh="美国工业部门电力销售量"),
    _usgov("eia/electricity_sales/US.RES", ("energy", "consumption"),
           _ELEC_KW + ("residential electricity sales", "household electricity", "居民用电"),
           title_suffix="U.S. total, residential sector", title_zh="美国居民部门电力销售量"),
    _usgov("eia/electricity_sales/VA.COM", ("energy", "technology"),
           _DATA_CENTER_KW + ("virginia electricity", "data center alley", "northern virginia", "弗吉尼亚州用电"),
           title_suffix="Virginia, commercial sector", title_zh="弗吉尼亚州商业部门电力销售量"),
    _usgov("eia/electricity_sales/TX.COM", ("energy", "technology"),
           _DATA_CENTER_KW + ("texas electricity", "ercot", "得克萨斯州用电"),
           title_suffix="Texas, commercial sector", title_zh="得克萨斯州商业部门电力销售量"),
    _usgov("eia/electricity_price/US.ALL", ("energy", "inflation"),
           ("electricity price", "average electricity price", "retail electricity price", "power price", "电价",
            "平均电价"),
           title_suffix="U.S. total, all sectors", title_zh="美国平均零售电价（全部部门）"),
    _usgov("eia/electricity_price/US.COM", ("energy", "inflation"),
           ("commercial electricity price", "business electricity price", "商业电价"),
           title_suffix="U.S. total, commercial sector", title_zh="美国商业部门平均电价"),
    _usgov("eia/electricity_price/US.IND", ("energy", "inflation"),
           ("industrial electricity price", "industrial power price", "工业电价"),
           title_suffix="U.S. total, industrial sector", title_zh="美国工业部门平均电价"),
    _usgov("eia/electricity_price/US.RES", ("energy", "inflation"),
           ("residential electricity price", "household electricity price", "居民电价"),
           title_suffix="U.S. total, residential sector", title_zh="美国居民部门平均电价"),
    _usgov("eia/net_generation/ALL", ("energy",),
           ("electricity generation", "power generation", "net generation", "发电量", "总发电量"),
           title_suffix="all fuels", title_zh="美国总发电量"),
    _usgov("eia/net_generation/NG", ("energy",),
           ("natural gas generation", "gas-fired generation", "gas power", "燃气发电"),
           title_suffix="natural gas", title_zh="美国天然气发电量"),
    _usgov("eia/net_generation/COW", ("energy",),
           ("coal generation", "coal-fired generation", "coal power", "燃煤发电", "煤电"),
           title_suffix="all coal products", title_zh="美国燃煤发电量"),
    _usgov("eia/net_generation/SUN", ("energy",),
           ("solar generation", "solar power", "solar output", "太阳能发电", "光伏发电"),
           title_suffix="solar (utility-scale)", title_zh="美国太阳能发电量（公用事业规模）"),
    _usgov("eia/net_generation/WND", ("energy",),
           ("wind generation", "wind power", "wind output", "风力发电", "风电"),
           title_suffix="wind", title_zh="美国风力发电量"),
    _usgov("eia/net_generation/NUC", ("energy",),
           ("nuclear generation", "nuclear power", "nuclear output", "核电", "核能发电"),
           title_suffix="nuclear", title_zh="美国核电发电量"),
    _usgov("eia/crude_production", ("energy", "production"),
           ("crude oil production", "oil production", "us oil output", "shale oil", "原油产量", "石油产量")),
    _usgov("eia/generating_capacity/BAT", ("energy",),
           ("battery storage", "battery storage capacity", "grid storage", "energy storage", "utility-scale batteries",
            "储能", "电池储能", "储能装机"),
           title_suffix="battery storage", title_zh="美国电池储能装机容量"),
    _usgov("eia/generating_capacity/SOL", ("energy",),
           ("solar capacity", "solar installations", "installed solar", "光伏装机", "太阳能装机"),
           title_suffix="solar", title_zh="美国太阳能发电装机容量"),
    _usgov("eia/generating_capacity/WND", ("energy",),
           ("wind capacity", "installed wind", "风电装机"),
           title_suffix="wind", title_zh="美国风电装机容量"),
    _usgov("eia/generating_capacity/ALL", ("energy",),
           ("generating capacity", "power capacity", "installed capacity", "发电装机容量", "装机容量"),
           title_suffix="all energy sources", title_zh="美国发电装机总容量"),
    # BEA (advertised only with BEA_API_KEY); FRED mirrors are preferred where they exist
    _usgov("bea/real_gdp_growth", ("growth",),
           ("real gdp growth", "gdp growth", "national accounts", "nipa", "国民经济核算", "gdp增长"),
           preferred="fred:A191RL1Q225SBEA"),
    _usgov("bea/real_pce_growth", ("consumption", "growth"),
           ("real consumption growth", "pce growth", "consumer spending growth", "nipa", "消费增长"),
           preferred="fred:DPCERL1Q225SBEA"),
    _usgov("bea/personal_income", ("income",),
           ("personal income", "household income", "nipa", "个人收入")),
    _usgov("bea/nominal_pce", ("consumption",),
           ("personal consumption expenditures", "nominal consumption", "consumer spending", "nipa", "个人消费支出")),
    _usgov("bea/value_added_by_industry/51", ("technology", "growth"),
           ("information sector", "information industry", "tech sector gdp", "value added", "信息产业增加值"),
           title_suffix="Information (51)", title_zh="美国信息业增加值"),
    _usgov("bea/value_added_by_industry/514", ("technology", "growth"),
           ("data processing", "data centers", "data center industry", "cloud computing", "web hosting",
            "数据中心", "数据处理", "云计算"),
           title_suffix="Data processing, internet publishing, and other information services (514)",
           title_zh="美国数据处理、互联网出版及其他信息服务业增加值"),
    _usgov("bea/value_added_by_industry/334", ("technology", "production"),
           ("electronics industry", "computer and electronic products", "semiconductor industry value added",
            "电子产品制造业增加值"),
           title_suffix="Computer and electronic products (334)", title_zh="美国计算机和电子产品制造业增加值"),
    _usgov("bea/value_added_by_industry/22", ("energy", "growth"),
           ("utilities value added", "utility sector", "power utilities", "公用事业增加值"),
           title_suffix="Utilities (22)", title_zh="美国公用事业增加值"),
)

CATALOG: tuple[CatalogEntry, ...] = (
    _FRED_ENTRIES + _BLS_ENTRIES + _BIS_ENTRIES + _IMF_ENTRIES + _WB_ENTRIES + _USGOV_ENTRIES
)

_BY_ID: dict[str, CatalogEntry] = {entry.series: entry for entry in CATALOG}
_BY_CASEFOLD: dict[str, CatalogEntry] = {entry.series.casefold(): entry for entry in CATALOG}
_INDEX: dict[str, int] = {entry.series: position for position, entry in enumerate(CATALOG)}


_GEOGRAPHY_NAMES = frozenset(name.casefold() for name, _aliases in GEOGRAPHIES.values()) | {"euro area (ea)"}


def _statistic(title: str) -> str:
    """The title without its trailing geography ("GDP (annual % growth): World" -> "gdp (annual %
    growth)"), or "" when the title does not end in a geography name."""
    head, _sep, tail = title.rpartition(": ")
    return head.casefold() if head and tail.casefold() in _GEOGRAPHY_NAMES else ""


# World aggregate -> economies the catalog carries the same statistic for.  A world aggregate is a
# benchmark for a country question unless the catalog has the statistic for that country itself
# (world GDP growth is context, not an answer, for a China GDP question; the oil price is one).
_STATISTICS: dict[str, str] = {entry.series: _statistic(entry.title) for entry in CATALOG}
_WORLD_SIBLINGS: dict[str, frozenset[str]] = {
    world.series: frozenset(entry.geography for entry in CATALOG
                            if entry.geography != "WLD" and _STATISTICS[entry.series] == _STATISTICS[world.series])
    for world in CATALOG if world.geography == "WLD" and _STATISTICS[world.series]
}

# Headline series: ranked ahead of near-ties in search when a concept matches.
_CORE_IDS: tuple[str, ...] = (
    "fred:A191RL1Q225SBEA", "fred:CPIAUCSL", "fred:PCEPILFE", "fred:UNRATE", "fred:PAYEMS",
    "fred:FEDFUNDS", "fred:DGS10", "fred:T10Y2Y", "fred:DCOILBRENTEU", "fred:DTWEXBGS",
    "bis:WS_CBPOL/M.XM", "bis:WS_CBPOL/M.CN", "imf:WEO/G001.NGDP_RPCH.A", "wb:IMF_WEO_NGDP_RPCH/CHN",
    "fred:PCOPPUSDM", "usgov:treasury/debt_to_penny",
)
# Families preferred for forecasting when a concept matches (long official projections,
# cross-country policy rates) plus the headline ids above.
_PRIORITY_PREFIXES: tuple[str, ...] = (
    "wb:IMF_WEO_NGDP_RPCH/", "wb:IMF_WEO_PCPIPCH/", "wb:IMF_WEO_LUR/", "imf:WEO/", "bis:WS_CBPOL/",
)
_PRIORITY_IDS: frozenset[str] = frozenset(_CORE_IDS) | frozenset((
    "fred:CPILFESL", "fred:PCEPI", "fred:GDPC1", "fred:DFEDTARU", "fred:ECBDFR", "fred:DGS2", "fred:DCOILWTICO",
    "fred:MORTGAGE30US", "fred:CSUSHPISA", "fred:ICSA", "fred:JTSJOL", "fred:BOPGSTB", "fred:GFDEGDQ188S",
    "fred:IPG3344S", "bls:CUUR0000SA0", "bls:WPUFD4", "usgov:treasury/mts_deficit",
    "usgov:treasury/mts_customs_duties", "usgov:eia/electricity_sales/US.ALL", "usgov:eia/generating_capacity/BAT",
))
_PRIORITY_BONUS = 2.5
# One keyword-level match; topic or bigram overlap alone gets no headline bonus.  Public as the
# concept half of CatalogHit.strong (DataSources.search returns early only on strong hits).
STRONG_CONCEPT_SCORE = 4.0
_PRIORITY_MIN_CONCEPT = STRONG_CONCEPT_SCORE
_STRONG_COVERAGE = 2 / 3      # share of the query's concept terms a strong hit must explain
_ID_MATCH_SCORE = 40.0        # the query names the series id itself
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
    provider except usgov, whose recipes match case-insensitively.  Lookup ignores
    key availability (``entry_available``): it answers what an id means.
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

_CJK_RUN_RE = re.compile(r"[㐀-鿿]+")
_US_RE = re.compile(r"(?<![A-Za-z])U\.?S\.?A?(?![A-Za-z])")
_UK_RE = re.compile(r"(?<![A-Za-z])U\.?K\.?(?![A-Za-z])")
# Upper-case ISO3 codes (the form the planner digest prints, e.g. "policy rate CHN") and EA/EU.
_ISO3_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(GEOGRAPHIES)) + r"|EA|EU)(?![A-Za-z])")
_STOPWORDS = frozenset((
    "a", "about", "above", "after", "all", "also", "an", "and", "any", "are", "as", "at", "be", "been",
    "before", "being", "below", "between", "by", "can", "could", "data", "do", "does", "during", "each",
    "end", "for", "from", "has", "have", "how", "if", "in", "into", "is", "it", "its", "latest", "less",
    "level", "more", "most", "new", "next", "not", "of", "on", "or", "over", "per", "rate", "s", "series",
    "should", "still", "such", "than", "that", "the", "their", "then", "there", "these", "this", "those",
    "through", "throughout", "to", "total", "under", "until", "was", "what", "when", "where", "whether",
    "which", "while", "who", "why", "will", "with", "within", "would", "year", "years",
))


# Generic title words that say nothing about the concept ("Constant prices, Percent change").
_TITLE_NOISE = frozenset(_stem(word) for word in (
    "adjusted", "annual", "average", "basis", "change", "constant", "current", "daily", "dollars", "index",
    "monthly", "percent", "period", "prices", "quarterly", "seasonally", "units", "weekly",
))
# Question framing that no series measures: outcome and movement verbs and hedges ("will ... exceed",
# "how will ... evolve", "trend lower"), calendar words ("by December 2027") and magnitudes or units
# ("500 TWh").  Ignored when measuring how much of a query an entry explains (coverage), never used
# for scoring.
_FRAMING_WORDS = frozenset(_stem(word) for word in (
    "accelerate", "affect", "again", "ahead", "base", "beat", "become", "behave", "bottom", "chance", "change",
    "compare", "comparison", "continue", "cut", "decelerate", "decline", "develop", "direction", "drop", "ease",
    "effect", "estimate", "ever", "evolution", "evolve", "exceed", "expect", "fall", "first", "forecast", "grow",
    "happen", "high", "higher", "hike", "hit", "impact", "imply", "increase", "influence", "like", "likelihood",
    "likely", "look", "low", "lower", "many", "mean", "might", "move", "movement", "much", "odds", "outlook",
    "pace", "path", "peak", "perform", "performance", "persist", "predict", "prediction", "probability",
    "projected", "projection", "raise", "react", "reaction", "reach", "rebound", "record", "recover",
    "recovery", "remain", "respond", "response", "rise", "scenario", "shift", "since", "slow", "speed", "stay",
    "surpass", "tighten", "top", "trajectories", "trajectory", "trend", "turn", "versus", "vs",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "approximately", "around", "coming", "currently", "early", "eventually", "half",
    "late", "later", "least", "mid", "month", "near", "nearly", "now", "past", "quarter", "recent", "recently",
    "roughly", "soon", "today", "ultimately", "upcoming", "week",
    # sourcing and history requests ("drawing on IMF forecasts", "fed funds rate history"), causal
    # mechanisms ("will grid constraints slow the build-out") and "hold" ("will the ECB hold rates")
    "according", "based", "cite", "citing", "combine", "combined", "combining", "consider", "considering",
    "drawing", "historic", "historical", "historically", "history", "incorporate", "incorporating",
    "bottleneck", "build", "buildout", "constrain", "constraint", "out", "hold",
    "barrel", "bbl", "billion", "bp", "bps", "bushel", "gallon", "gw", "gwh", "kwh", "million", "mmbtu", "mw",
    "mwh", "ounce", "percent", "point", "pp", "thousand", "ton", "tonne", "trillion", "tw", "twh", "uk", "us",
    "yoy",
))
_FRAMING_ZH: tuple[str, ...] = (
    "是否", "超过", "达到", "突破", "跌破", "低于", "高于", "以上", "以下", "预测", "展望", "预计", "可能",
    "年底", "年末", "万亿", "多少", "什么", "怎样", "如何", "怎么", "变化", "变动", "走势", "趋势", "演变",
    "路径", "前景", "上升", "下降", "上涨", "下跌", "回落", "降至", "降到", "升至", "升到", "同比", "截至",
    "直到", "期间", "之前", "之后", "以来", "目前", "当前", "未来", "今年", "明年", "左右", "如果", "假如",
    "一旦", "那么", "结合", "根据", "参考", "依据", "基于", "按照", "考虑", "历史", "制约", "约束", "瓶颈",
    # single characters last, so the two-character terms above are removed whole ("前景" before "前")
    "亿", "会", "将", "吗", "呢", "的", "和", "与", "及", "或", "在", "对", "是", "了", "到", "年", "月", "前",
    "后", "个", "从", "为", "于", "等",
)


# What a series measures, by class: a price or a quantity.  A query naming one class ("electricity
# retail price") is never answered strongly by a series whose title names only the other ("Retail
# Sales of Electricity"), unless its keywords make the query's word a synonym (electricity sales
# are electricity consumption).
_MEASURE_CLASSES: dict[str, str] = {
    **{word: "price" for word in ("price", "cost")},
    **{word: "quantity" for word in ("sale", "consumption", "demand", "usage", "generation", "production",
                                     "output", "capacity", "shipment", "volume")},
}


def _measure_classes(words: frozenset[str] | set[str]) -> frozenset[str]:
    return frozenset(_MEASURE_CLASSES[word] for word in words if word in _MEASURE_CLASSES)


# Maturity-style tenors ("10-year", "3-month", "10年期", "3个月期"): a query naming one tenor is never
# answered strongly by a series of another tenor (DGS2 for a 10-year question).
_TENOR_EN_RE = re.compile(r"(\d+)-(year|month)")
_TENOR_ZH_RE = re.compile(r"(\d+)(年|个月)期")


def _tenors(text: str) -> frozenset[str]:
    lowered = _cjk_numerals(text or "").lower()
    found = {f"{n}{unit}" for n, unit in _TENOR_EN_RE.findall(lowered)}
    found.update(f"{n}{'year' if unit == '年' else 'month'}" for n, unit in _TENOR_ZH_RE.findall(lowered))
    return frozenset(found)


def _ascii_words(text: str) -> list[str]:
    return [_stem(word) for word in _WORD_RE.findall(text.lower())]


def _phrase(text: str) -> str:
    return " ".join(_ascii_words(text))


def _cjk_bigrams(text: str) -> frozenset[str]:
    grams: set[str] = set()
    for run in _CJK_RUN_RE.findall(text):
        grams.update(run[i:i + 2] for i in range(len(run) - 1))
    return frozenset(grams)


def _term_hit(term: str, padded: str, compact: str) -> bool:
    """True when ``term`` (an EN phrase or a CJK term) occurs in the query."""
    if _CJK_RE.search(term):
        return "".join(term.lower().split()) in compact
    phrase = _phrase(term)
    return bool(phrase) and f" {phrase} " in padded


_GEO_WORDS = frozenset(word for _name, aliases in GEOGRAPHIES.values() for alias in aliases
                       if not _CJK_RE.search(alias) for word in _ascii_words(alias) if word not in _STOPWORDS)
_GEO_ZH: tuple[str, ...] = tuple(sorted({alias for _name, aliases in GEOGRAPHIES.values() for alias in aliases
                                         if _CJK_RE.search(alias)}, key=len, reverse=True))
# Every alias, longest first: a matched alias consumes its text, so "中国香港" names Hong Kong (not
# also China), "印度尼西亚" Indonesia (not also India) and "Taiwan, China" Taiwan alone.
_GEO_ALIASES: tuple[tuple[str, str], ...] = tuple(sorted(
    ((alias, code) for code, (_name, aliases) in GEOGRAPHIES.items() for alias in aliases),
    key=lambda item: (-len(item[0]), item[0])))
_PUBLISHER_RE = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(re.escape(name).replace(r"\ ", r"[\s-]+")
                                   for name in sorted(_PUBLISHER_NAMES, key=len, reverse=True))
    + r")(?![A-Za-z])|(?<![A-Za-z])(?-i:" + "|".join(_PUBLISHER_ACRONYMS) + r")(?![A-Za-z])",
    re.IGNORECASE)
_PUBLISHERS_ZH_LONGEST = tuple(sorted(_PUBLISHERS_ZH, key=len, reverse=True))


def _without_publishers(text: str) -> str:
    """``text`` with publisher and organisation names blanked (see ``_PUBLISHER_NAMES``)."""
    text = _PUBLISHER_RE.sub(" ", text)
    for name in _PUBLISHERS_ZH_LONGEST:
        text = text.replace(name, " ")
    return text


def _geographies(raw: str, padded: str, compact: str) -> frozenset[str]:
    """Geography codes named in a publisher-free query, longest alias first (see _GEO_ALIASES)."""
    geos = set()
    if _US_RE.search(raw):
        geos.add("USA")
    if _UK_RE.search(raw):
        geos.add("GBR")
    for code in _ISO3_RE.findall(raw):
        geos.add("EMU" if code in ("EA", "EU") else code)
    for alias, code in _GEO_ALIASES:
        if _CJK_RE.search(alias):
            key = "".join(alias.split())
            if key in compact:
                geos.add(code)
                compact = compact.replace(key, "\0")
        else:
            phrase = _phrase(alias)
            if phrase and f" {phrase} " in padded:
                geos.add(code)
                padded = padded.replace(f" {phrase} ", " \0 ")
    return frozenset(geos)


@dataclass(frozen=True)
class _Query:
    raw_lower: str
    padded: str        # " stemmed ascii words "
    compact: str       # lowercase, whitespace removed (CJK substring matching)
    words: frozenset[str]
    bigrams: frozenset[str]
    geos: frozenset[str]
    concept_words: frozenset[str]  # words a series could explain (no geography, framing or digits)
    concept_chars: frozenset[str]  # CJK characters a series could explain (same exclusions)
    tenors: frozenset[str]         # maturity tenors the query names ("10year")
    topics: frozenset[str]         # TOPICS the query triggers


_TOPIC_TERMS: tuple[tuple[str, str], ...] = tuple(sorted(
    ((term, topic) for topic, terms in TOPICS.items() for term in terms), key=lambda item: -len(item[0])))
# Multi-word English topic terms ("data center", "new energy vehicle"): a stopword that modifies one
# a query or a title names is part of the concept ("data" of "data center"), not filler.  The head
# word stays generic ("rate" of "policy rate").
_COMPOUND_TERMS: tuple[str, ...] = tuple(sorted({_phrase(term) for terms in TOPICS.values() for term in terms
                                                if " " in term and not _CJK_RE.search(term)}))


def _modifier_words(padded: str) -> frozenset[str]:
    """Modifier words of the multi-word topic terms in ``padded`` (" stemmed ascii words ")."""
    return frozenset(word for phrase in _COMPOUND_TERMS if f" {phrase} " in padded
                     for word in phrase.split()[:-1])


def _query_topics(padded: str, compact: str) -> frozenset[str]:
    """Topics whose terms occur in the query, longest term first.  A matched CJK term consumes
    its characters and a matched multi-word English term its words, so the "能源" inside
    "新能源汽车" and the "energy" inside "new energy vehicles" do not also trigger the energy
    topic, and "policy rate" or "exchange rate" not also the interest-rate topic."""
    found: set[str] = set()
    for term, topic in _TOPIC_TERMS:
        if _CJK_RE.search(term):
            key = "".join(term.lower().split())
            if key in compact:
                found.add(topic)
                compact = compact.replace(key, "\0")
        elif _term_hit(term, padded, compact):
            found.add(topic)
            if " " in term:
                padded = padded.replace(f" {_phrase(term)} ", " \0 ")
    return frozenset(found)


def _parse_query(query: str) -> _Query:
    raw = _cjk_numerals(query or "")
    lowered = raw.lower()
    padded = f" {' '.join(_ascii_words(raw))} "
    compact = "".join(lowered.split())
    # Keywords and bigrams read the whole text, so a publisher still selects its own series ("imf
    # forecast", "世界银行预测"); geographies, topics and concept terms read it without publishers.
    named = _without_publishers(raw)
    tokens = _ascii_words(named)
    named_padded = f" {' '.join(tokens)} "
    named_compact = "".join(named.lower().split())
    iso_words = {code.lower() for code in _ISO3_RE.findall(named)}
    modifiers = _modifier_words(named_padded)
    words = frozenset(word for word in tokens
                      if (word not in _STOPWORDS or word in modifiers) and word not in _GEO_WORDS
                      and word not in iso_words and not word.isdigit())
    cjk_text = "".join(_CJK_RUN_RE.findall(named))
    for term in _GEO_ZH + _FRAMING_ZH:
        cjk_text = cjk_text.replace(term, " ")
    return _Query(raw_lower=lowered, padded=padded, compact=compact, words=words,
                  bigrams=_cjk_bigrams(raw), geos=_geographies(named, named_padded, named_compact),
                  concept_words=frozenset(word for word in words
                                          if word not in _FRAMING_WORDS and not any(ch.isdigit() for ch in word)),
                  concept_chars=frozenset(ch for ch in cjk_text if _CJK_RE.match(ch)),
                  tenors=_tenors(raw), topics=_query_topics(named_padded, named_compact))


def query_geographies(query: str) -> frozenset[str]:
    """Catalog geography codes a query names: whole-word EN aliases, ZH names, "US"/"UK"
    and upper-case ISO3 codes ("CHN", "EA").  Substrings never count ("fedex" is not the Fed),
    the longest alias wins ("中国香港" is Hong Kong alone) and publishers are no places ("World
    Bank", "世界银行", "IMF", "OECD", "United Nations")."""
    return _parse_query(query).geos


# Clause boundaries of a compound question ("Will US CPI fall below 2.5% ..., and how will the Fed
# policy rate evolve?"): sentence ends (not the "S." of "U.S."), question marks, semicolons, colons,
# ", and/but/or/while/whereas", "and/but" before a new question word, and CJK commas.
_CLAUSE_RE = re.compile(
    r"(?<!\b[A-Za-z])\.(?=\s|$)|[?!;。？！；：\n]+|:\s|,\s*(?:and|but|or|while|whereas)\s+"
    r"|\s+(?:and|but)\s+(?=(?:how|what|when|where|whether|which|who|why|will|would|could|can|should|does|do"
    r"|did|is|are)\b)"
    r"|[，、]",
    re.IGNORECASE)
_MAX_CLAUSES = 8
_SPACE_RUN_RE = re.compile(r"\s+")


def _clause_space(match: re.Match) -> str:
    """A whitespace run shortened for _CLAUSE_RE: the kind (newline or other) of its first
    character, then the kinds the rest holds.  The split depends on nothing else: ":\\s" takes
    the first character, a newline splits, and any other whitespace character lets a following
    "and/but <question word>" go with the run.  Clauses are compared whitespace-normalised, so
    they stay identical while a long run no longer costs a rescan from each of its positions."""
    run = match.group()
    rest = run[1:]
    return ("\n" if run[0] == "\n" else " ") + (" " if rest.strip("\n") else "") + ("\n" if "\n" in rest else "")


# Coordinated phrases inside one clause ("will grid and power-price constraints slow the buildout",
# "US unemployment and inflation"): each names its own concept, so an entry answering one of them
# fully answers the clause.  English only: 和/与/及 also occur inside Chinese words.  A match
# starts only where a whitespace run starts ((?<!\s): a later start would reach the same run end
# and fail or succeed alike), which keeps long whitespace runs linear.
_CONJUNCT_RE = re.compile(r"(?<!\s)\s+(?:and|or)\s+|(?<!\s)\s+&\s+", re.IGNORECASE)
_MAX_CONJUNCTS = 4


@dataclass(frozen=True)
class _Part:
    text: str          # the clause as written ("" for the whole query)
    query: _Query
    conjuncts: tuple[_Query, ...] = ()   # its coordinated phrases (two or more naming a concept)


def _conjuncts(text: str, geos: frozenset[str]) -> tuple[_Query, ...]:
    """The coordinated phrases of a clause that name a concept, when at least two do; a phrase
    naming no geography inherits the clause's."""
    found: list[_Query] = []
    for piece in _CONJUNCT_RE.split(text or ""):
        parsed = _parse_query(piece)
        if parsed.concept_words or parsed.concept_chars:
            found.append(parsed if parsed.geos else replace(parsed, geos=geos))
    return tuple(found[:_MAX_CONJUNCTS]) if len(found) >= 2 else ()


def _query_parts(query: str) -> tuple[_Part, ...]:
    """The whole query, then -- for a compound question with at least two clauses that each
    name a concept -- every such clause (at most ``_MAX_CLAUSES``), ranked on its own.  A clause
    naming no geography inherits the question's ("how will the policy rate evolve").  A clause
    (or a single-clause query) also carries its coordinated phrases (:func:`_conjuncts`)."""
    whole = _parse_query(query)
    clauses: list[_Part] = []
    seen: set[str] = set()
    for piece in _CLAUSE_RE.split(_SPACE_RUN_RE.sub(_clause_space, query or "")):
        text = " ".join(piece.split())
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        parsed = _parse_query(text)
        if not (parsed.concept_words or parsed.concept_chars):
            continue
        if not parsed.geos:
            parsed = replace(parsed, geos=whole.geos)
        clauses.append(_Part(text=text, query=parsed, conjuncts=_conjuncts(text, parsed.geos)))
    if len(clauses) < 2:
        return (_Part(text="", query=whole, conjuncts=_conjuncts(query, whole.geos)),)
    return (_Part(text="", query=whole), *clauses[:_MAX_CLAUSES])


@dataclass(frozen=True)
class _EntryTerms:
    title_words: frozenset[str]
    zh_bigrams: frozenset[str]
    native_lower: str
    tenors: frozenset[str]
    measures: frozenset[str]   # measure classes its title and keywords name ("price", "quantity")


def _title_words(title: str) -> frozenset[str]:
    words = _ascii_words(title)
    modifiers = _modifier_words(f" {' '.join(words)} ")
    return frozenset(word for word in words
                     if (word not in _STOPWORDS or word in modifiers) and word not in _GEO_WORDS
                     and word not in _TITLE_NOISE and not word.isdigit() and len(word) > 2)


_ENTRY_TERMS: dict[str, _EntryTerms] = {
    entry.series: _EntryTerms(
        title_words=_title_words(entry.title),
        zh_bigrams=_cjk_bigrams(entry.title_zh),
        native_lower=entry.native.lower(),
        tenors=_tenors(" ".join((entry.title, entry.title_zh, *entry.keywords))),
        measures=_measure_classes(set(_ascii_words(" ".join((entry.title, *entry.keywords))))),
    )
    for entry in CATALOG
}


def _concept(entry: CatalogEntry, query: _Query) -> tuple[float, float]:
    """(concept score, coverage) of ``entry`` for ``query``; see :class:`CatalogHit`.
    A tenor the query names but the entry contradicts leaves coverage at 0, and so does a measure
    class the query names but the entry neither explains nor names while naming the other one
    (a price question answered by a sales series)."""
    terms = _ENTRY_TERMS[entry.series]
    score = 0.0
    if entry.series.lower() in query.raw_lower:
        score += 100.0
    elif len(terms.native_lower) >= 5 and re.search(
            rf"(?<![a-z0-9_]){re.escape(terms.native_lower)}(?![a-z0-9_])", query.raw_lower):
        score += _ID_MATCH_SCORE
    covered_words = set(terms.title_words & query.words)
    covered_chars: set[str] = set()
    for keyword in entry.keywords:
        if _term_hit(keyword, query.padded, query.compact):
            if _CJK_RE.search(keyword):
                score += 4.0 + 0.5 * max(0, len(keyword) - 2)
                covered_chars.update(keyword)
            else:
                score += 4.0 + 1.5 * (len(keyword.split()) - 1)
                covered_words.update(_ascii_words(keyword))
    score += 1.0 * min(3, len(terms.title_words & query.words))
    shared = terms.zh_bigrams & query.bigrams
    score += 0.75 * min(6, len(shared))
    for gram in shared:
        covered_chars.update(gram)
    score += 2.0 * len(query.topics.intersection(entry.topics))
    if query.tenors and terms.tenors and not query.tenors & terms.tenors:
        return score, 0.0
    if _measure_classes(query.concept_words - covered_words) - terms.measures and terms.measures:
        return score, 0.0
    total = len(query.concept_words) + len(query.concept_chars)
    explained = len(query.concept_words & covered_words) + len(query.concept_chars & covered_chars)
    return score, (explained / total if total else 0.0)


def _priority(entry: CatalogEntry) -> bool:
    return entry.series in _PRIORITY_IDS or entry.series.startswith(_PRIORITY_PREFIXES)


def _score(entry: CatalogEntry, query: _Query, concept: float) -> float:
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


@dataclass(frozen=True)
class CatalogHit:
    """One ranked catalog match.

    ``score`` is the concept strength plus the headline bonus and geography fit; it orders
    the results of a single-clause query.  ``concept`` is the concept strength alone: 4.0 is
    one keyword-level match, topic or title overlap scores less.  ``coverage`` is the share of
    the query's concept terms (English words and CJK characters; geography, digits and question
    framing such as "will ... exceed", "how will ... evolve", "by December" or "TWh" ignored)
    that the entry's keywords and titles explain.  ``strong`` marks a hit that answers the
    query on its own: the series id itself, or concept >= ``STRONG_CONCEPT_SCORE`` with
    coverage >= 2/3 in the asked-about geography (or a world benchmark) and no contradicting
    tenor ("10-year" vs a 2-year series).  For a compound question the fields describe the
    clause the entry answers best (:func:`search_catalog_scored`).  Weak hits are discovery
    hints; consult live provider search too.
    """
    entry: CatalogEntry
    score: float
    concept: float
    coverage: float
    strong: bool


@dataclass(frozen=True)
class _Match:
    hit: CatalogHit
    direct: bool   # keyword-level match explaining part of its clause, in the clause's geography


@dataclass(frozen=True)
class _Ranking:
    parts: tuple[_Part, ...]
    answered: tuple[bool, ...]   # per part: at least one strong match
    matches: tuple[_Match, ...]


# A central bank's balance sheet (total assets) is not its policy rate: "central bank" in the title
# plus the policy topic reach the strong score, so a rate question ("cut rates", "利率", "降息")
# that names no balance-sheet term never takes a balance-sheet series as a strong match.
_BALANCE_SHEET_IDS: frozenset[str] = frozenset(
    entry.series for entry in CATALOG
    if any("balance sheet" in keyword or "资产负债表" in keyword for keyword in entry.keywords))
_RATE_QUERY_RE = re.compile(r"(?<![a-z])(?:rates?|interest|cuts?|hikes?)(?![a-z])|利率|降息|加息")
_BALANCE_SHEET_QUERY_RE = re.compile(
    r"balance[\s-]+sheets?|(?<![a-z])(?:assets?|holdings?|quantitative|qt|qe|runoff)(?![a-z])"
    r"|资产负债表|缩表|扩表|总资产|量化")


def _match(entry: CatalogEntry, query: _Query) -> _Match | None:
    concept, coverage = _concept(entry, query)
    score = round(_score(entry, query, concept), 6)
    if score < _MIN_HIT_SCORE:
        return None
    fits = not query.geos or entry.geography in query.geos or (
        entry.geography == "WLD" and not _WORLD_SIBLINGS.get(entry.series, frozenset()) & query.geos)
    strong = concept >= _ID_MATCH_SCORE or (
        concept >= STRONG_CONCEPT_SCORE and coverage >= _STRONG_COVERAGE and fits
        and not (entry.series in _BALANCE_SHEET_IDS and _RATE_QUERY_RE.search(query.raw_lower)
                 and not _BALANCE_SHEET_QUERY_RE.search(query.raw_lower)))
    explains = coverage > 0 or not (query.concept_words or query.concept_chars)
    return _Match(hit=CatalogHit(entry=entry, score=score, concept=round(concept, 6),
                                 coverage=round(coverage, 4), strong=strong),
                  direct=strong or (concept >= STRONG_CONCEPT_SCORE and fits and explains))


def _match_rank(match: _Match) -> tuple[bool, bool, float]:
    return match.hit.strong, match.direct, match.hit.score


def _part_match(entry: CatalogEntry, part: _Part) -> _Match | None:
    """The entry's best match for a clause: strong and direct when the clause itself or one of its
    coordinated phrases makes it so, ranked by its best score (a phrase match never lowers it)."""
    matches = [match for match in (_match(entry, query) for query in (part.query, *part.conjuncts)) if match]
    if not matches:
        return None
    best = max(matches, key=_match_rank)
    score = max(match.hit.score for match in matches)
    return best if score == best.hit.score else replace(best, hit=replace(best.hit, score=score))


def _score_order(match: _Match) -> tuple[float, int]:
    return -match.hit.score, _INDEX[match.hit.entry.series]


def _ranking(query: str, provider: str | None, env: Mapping[str, str] | None) -> _Ranking:
    wanted = (provider or "").strip().lower() or None
    if not (query or "").strip() or (wanted is not None and wanted not in PROVIDERS):
        return _Ranking(parts=(), answered=(), matches=())
    parts = _query_parts(query)
    best: dict[str, _Match] = {}
    strong: list[list[_Match]] = [[] for _ in parts]
    for entry in CATALOG:
        if (wanted is not None and entry.provider != wanted) or not entry_available(entry, env=env):
            continue
        for index, part in enumerate(parts):
            match = _part_match(entry, part)
            if match is None:
                continue
            if match.hit.strong:
                strong[index].append(match)
            current = best.get(entry.series)
            if current is None or _match_rank(match) > _match_rank(current):
                best[entry.series] = match
    # Strong matches lead.  Per clause of a compound question: the clauses' strong matches take
    # turns (question order), so a later clause's series are never crowded out by near-duplicates
    # of an earlier clause; strong matches of the whole question alone follow, then everything
    # else by score.
    queues = [sorted(rows, key=_score_order) for rows in strong[1:]]
    lead: list[_Match] = []
    taken: set[str] = set()
    while any(queues):
        for queue in queues:
            while queue and queue[0].hit.entry.series in taken:
                queue.pop(0)
            if queue:
                series = queue.pop(0).hit.entry.series
                taken.add(series)
                lead.append(best[series])
    lead += [best[match.hit.entry.series] for match in sorted(strong[0], key=_score_order)
             if match.hit.entry.series not in taken]
    taken.update(match.hit.entry.series for match in strong[0])
    ranked = lead + [match for match in sorted(best.values(), key=_score_order)
                     if match.hit.entry.series not in taken]
    # A faster equivalent route (FRED mirror of an IMF commodity price, Data360 copy of a WEO
    # series) is listed directly ahead of the entry that names it.
    by_id = {match.hit.entry.series: match for match in ranked}
    ordered: list[_Match] = []
    placed: set[str] = set()
    for match in ranked:
        fast = match.hit.entry.preferred
        if fast in by_id and fast not in placed:
            ordered.append(by_id[fast])
            placed.add(fast)
        if match.hit.entry.series not in placed:
            ordered.append(match)
            placed.add(match.hit.entry.series)
    return _Ranking(parts=parts, answered=tuple(bool(rows) for rows in strong), matches=tuple(ordered))


def search_catalog_scored(query: str, *, provider: str | None = None, limit: int = 8,
                          env: Mapping[str, str] | None = None) -> list[CatalogHit]:
    """Ranked :class:`CatalogHit` rows for ``query`` (EN or ZH); ties keep catalog order and a
    ``preferred`` fast route precedes the entry naming it.

    A compound question ("Will US CPI fall below 2.5% ..., and how will the Fed policy rate
    evolve?") is also ranked clause by clause: each entry keeps its best clause, the clauses'
    strong matches take turns at the top (question order), so every clause's series rank early,
    and the whole question's other strong matches follow.  A clause naming no geography
    inherits the question's.  ``provider`` restricts the search to one provider id; an unknown
    provider or an empty query returns [].  Entries whose provider key is missing from ``env``
    (default ``os.environ``; EIA/BEA recipes) are not returned.
    """
    if limit <= 0:
        return []
    return [match.hit for match in _ranking(query, provider, env).matches[:limit]]


def search_catalog(query: str, *, provider: str | None = None, limit: int = 8,
                   env: Mapping[str, str] | None = None) -> list[CatalogEntry]:
    """The entries of :func:`search_catalog_scored`, best first."""
    return [hit.entry for hit in search_catalog_scored(query, provider=provider, limit=limit, env=env)]


# Chinese concept terms -> English provider-search terms (FRED search is English-only).
# Greedy longest match; place names come from GEOGRAPHIES.
_ZH_EN_TERMS: dict[str, str] = {
    "半导体": "semiconductor", "芯片": "semiconductor", "集成电路": "integrated circuits", "晶圆": "wafer",
    "数据中心": "data center", "人工智能": "artificial intelligence", "算力": "computing capacity",
    "云计算": "cloud computing", "电子产品": "electronics", "计算机": "computer",
    "用电量": "electricity consumption", "用电": "electricity consumption", "电力需求": "electricity demand",
    "电力消费": "electricity consumption", "售电量": "electricity sales", "发电量": "electricity generation",
    "发电": "electricity generation", "电力": "electricity", "电价": "electricity price", "电网": "power grid",
    "储能": "energy storage", "电池": "battery", "动力电池": "battery", "锂": "lithium", "碳酸锂": "lithium",
    "镍": "nickel", "钴": "cobalt", "铜": "copper", "铝": "aluminum", "铁矿石": "iron ore", "黄金": "gold",
    "光伏": "solar", "太阳能": "solar", "风电": "wind power", "风力": "wind power", "核电": "nuclear power",
    "煤炭": "coal", "煤": "coal", "可再生能源": "renewable energy", "新能源": "clean energy",
    "新能源汽车": "electric vehicle", "电动汽车": "electric vehicle", "汽车": "vehicle", "销量": "sales",
    "销售": "sales", "产量": "production", "生产": "production", "出货": "shipments", "订单": "orders",
    "产能": "capacity", "装机": "installed capacity", "利用率": "utilization",
    "关税": "tariff", "海关": "customs", "出口": "exports", "进口": "imports", "贸易": "trade",
    "贸易逆差": "trade deficit", "贸易顺差": "trade surplus",
    "通胀": "inflation", "通货膨胀": "inflation", "物价": "prices", "价格": "price", "消费者价格指数": "consumer price index",
    "失业率": "unemployment rate", "失业": "unemployment", "就业": "employment", "非农": "nonfarm payrolls",
    "工资": "wages", "国内生产总值": "gdp", "经济增长": "economic growth", "增长": "growth", "增速": "growth",
    "实际": "real", "衰退": "recession",
    "利率": "interest rate", "政策利率": "policy rate", "国债收益率": "treasury yield", "收益率": "yield",
    "国债": "treasury", "年期": "year", "债务": "debt", "赤字": "deficit", "财政": "fiscal", "税收": "tax revenue",
    "汇率": "exchange rate", "人民币": "renminbi", "美元": "dollar", "日元": "yen", "欧元": "euro",
    "房价": "house prices", "房地产": "real estate", "住房": "housing", "股市": "stock market", "股票": "stocks",
    "零售": "retail sales", "消费": "consumption", "投资": "investment", "工业": "industrial",
    "制造业": "manufacturing", "人口": "population", "排放": "emissions", "碳排放": "carbon emissions",
    "原油": "crude oil", "石油": "oil", "天然气": "natural gas", "能源": "energy", "油价": "oil price",
    "信贷": "credit", "杠杆": "leverage", "央行": "central bank", "货币供应": "money supply",
    "美联储": "Federal Reserve", "人民银行": "People's Bank of China", "欧洲央行": "ECB", "日本央行": "Bank of Japan",
    "英格兰银行": "Bank of England", "加息": "rate hike", "降息": "rate cut",
    "占比": "share", "份额": "share", "市场份额": "market share", "渗透率": "share", "销售额": "sales",
    "存款便利利率": "deposit facility rate", "存款利率": "deposit rate",
    "世界银行": "World Bank", "国际货币基金组织": "IMF", "国际货币基金": "IMF",
}
_ZH_EN: dict[str, str] = {**{alias: name for name, aliases in GEOGRAPHIES.values() for alias in aliases
                             if _CJK_RE.search(alias)}, **_ZH_EN_TERMS}
_ZH_EN_MAX = max(len(term) for term in _ZH_EN)


def english_query(query: str) -> str:
    """English rendering of a (partly) Chinese query for English-only provider search.

    Known concept and place terms map to English (greedy longest match), other CJK text
    is dropped, ASCII words and numbers stay: ``"中国半导体出口"`` -> ``"China semiconductor
    exports"``, ``"美国十年期国债收益率"`` -> ``"United States 10 year treasury yield"``.
    A query without CJK text is returned unchanged (stripped).
    """
    text = _cjk_numerals((query or "").strip())
    if not _CJK_RE.search(text):
        return (query or "").strip()
    terms: list[str] = []
    for piece in re.split(r"([㐀-鿿]+)", text):
        if not _CJK_RE.match(piece or " "):
            terms.extend(piece.split())
            continue
        position = 0
        while position < len(piece):
            for length in range(min(_ZH_EN_MAX, len(piece) - position), 0, -1):
                term = _ZH_EN.get(piece[position:position + length])
                if term:
                    terms.append(term)
                    position += length
                    break
            else:
                position += 1
    unique: list[str] = []
    for term in terms:
        if term not in unique:
            unique.append(term)
    return " ".join(unique)


# Compound topic term -> its topic ("new energy vehicle" -> autos), for the modifiers of a query, and
# the one-word terms of each topic: a modifier that is itself a term of its compound's topic names the
# subject ("electricity" of "electricity demand"), any other only qualifies it ("energy" of "new energy
# vehicle", "data" of "data center", "interest" of "interest rate").
_COMPOUND_TOPICS: dict[str, str] = {_phrase(term): topic for topic, terms in TOPICS.items() for term in terms
                                    if " " in term and not _CJK_RE.search(term)}
_TOPIC_WORDS: dict[str, frozenset[str]] = {topic: frozenset(_phrase(term) for term in terms
                                                            if " " not in term and not _CJK_RE.search(term))
                                           for topic, terms in TOPICS.items()}
# Measure words that need a subject ("semiconductor sales"): a title sharing only one of them with
# a query that names its subject ("Retail sales") measures something else.
_GENERIC_TERMS = frozenset(_stem(word) for word in (
    "balance", "capacity", "consumption", "cost", "demand", "expenditure", "exports", "flows", "growth",
    "imports", "index", "number", "output", "price", "production", "ratio", "revenue", "sales", "share",
    "spending", "stock", "supply", "usage", "use", "value", "volume",
))
_SAME_WORD_PREFIX = 7    # "electric" ~ "electricity", "industrial" ~ "industry"


@dataclass(frozen=True)
class ConceptTerms:
    """English concept terms of a search query (:func:`concept_terms`), for judging a provider's
    discovery hit by its title (:func:`shares_concept`).  ``specific`` names what is measured
    ("semiconductor", "vehicle", "electricity"); ``generic`` the measure ("sale", "share"); ``modifiers``
    pairs the qualifying modifier words of the compound topic terms the query names with that term's
    topic ("energy" of "new energy vehicle": autos).  Words are stemmed."""
    specific: frozenset[str]
    generic: frozenset[str]
    modifiers: tuple[tuple[str, str], ...]


def concept_terms(query: str) -> ConceptTerms:
    """The concept terms of ``query`` (EN or ZH): its English rendering (:func:`english_query`)
    without geography, publishers, question framing, dates and stopwords."""
    english = english_query(query)
    parsed = _parse_query(english)
    padded = f" {' '.join(_ascii_words(_without_publishers(_cjk_numerals(english))))} "
    modifiers = tuple(sorted({(word, topic) for phrase, topic in _COMPOUND_TOPICS.items() if f" {phrase} " in padded
                              for word in phrase.split()[:-1] if word not in _TOPIC_WORDS[topic]}))
    words = parsed.concept_words - {word for word, _topic in modifiers}
    return ConceptTerms(specific=frozenset(words - _GENERIC_TERMS), generic=frozenset(words & _GENERIC_TERMS),
                        modifiers=modifiers)


def _same_word(left: str, right: str) -> bool:
    if left == right:
        return True
    return min(len(left), len(right)) >= _SAME_WORD_PREFIX and left[:_SAME_WORD_PREFIX] == right[:_SAME_WORD_PREFIX]


def shares_concept(terms: ConceptTerms, title: str) -> bool | None:
    """Whether a provider hit titled ``title`` shares a concept with the query of ``terms``: a
    specific term; a compound's modifier when the title is about that compound's topic
    ("Renewable energy consumption" shares only "energy" with "new energy vehicle sales" and is
    about energy, not autos); or, when the query names no specific term, a measure word.  None
    when the query names no concept term at all (nothing to judge)."""
    if not (terms.specific or terms.generic or terms.modifiers):
        return None
    tokens = _ascii_words(title or "")
    words = {word for word in tokens if word not in _STOPWORDS}

    def shared(candidates) -> bool:
        return any(_same_word(word, term) for word in words for term in candidates)

    if shared(terms.specific):
        return True
    topics = _query_topics(f" {' '.join(tokens)} ", "".join((title or "").lower().split()))
    if any(topic in topics and shared((word,)) for word, topic in terms.modifiers):
        return True
    return not terms.specific and shared(terms.generic)


# ---------------------------------------------------------------------------
# Planner digest and skill reference
# ---------------------------------------------------------------------------

_DIGEST_MAX_CHARS = 6000
_DIGEST_TITLE_MAX = 90
_DIGEST_MIN_PICKS = 6          # fewer direct matches -> up to _DIGEST_RELATED_MAX related entries
_DIGEST_RELATED_MAX = 8
_DIGEST_RELATED_BESIDE = 4     # related entries kept beside _DIGEST_MIN_PICKS or more direct matches
_DIGEST_CLAUSE_MAX = 120       # chars of an unanswered clause quoted in the search hint


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _digest_line(entry: CatalogEntry) -> str:
    facets = [entry.units, entry.frequency]
    if entry.seasonal_adjustment:
        facets.append(entry.seasonal_adjustment)
    facets.append(entry.geography)
    return f"- {entry.series} — {_clip(entry.title, _DIGEST_TITLE_MAX)} ({', '.join(facets)})"


def _related(query: _Query, taken: set[str], env: Mapping[str, str] | None, limit: int) -> list[CatalogEntry]:
    """Entries sharing the question's economy and theme, beside the direct matches: same
    economy and theme, then world benchmarks of the theme, then (global or place-less
    questions) any economy's series whose main theme the question names; a question naming
    an economy but no theme gets that economy's headline series.  Never another economy's
    series when the question names one, and never another theme's series when it names one.
    Within a tier, stronger concept matches come first, then entries whose every theme the
    question names (electricity generation before electricity prices for an electricity-demand
    question)."""
    countries = query.geos - {"WLD"}

    def tier(entry: CatalogEntry) -> int | None:
        same_topic = bool(query.topics.intersection(entry.topics))
        if same_topic and entry.geography in countries:
            return 0
        if same_topic and entry.geography == "WLD":
            return 1
        if not countries and entry.topics[0] in query.topics:
            return 2
        if not query.topics and entry.geography in countries and _priority(entry):
            return 3
        return None

    ranked = []
    for entry in CATALOG:
        if entry.series in taken or not entry_available(entry, env=env):
            continue
        rank = tier(entry)
        if rank is not None:
            precision = len(query.topics.intersection(entry.topics)) / len(entry.topics)
            ranked.append((rank, -_concept(entry, query)[0], -precision, _INDEX[entry.series], entry))
    ranked.sort(key=lambda item: item[:4])
    return [item[4] for item in ranked[:max(0, limit)]]


def catalog_digest(question: str, *, limit: int = 40, env: Mapping[str, str] | None = None) -> str:
    """Compact, deterministic provider overview + the catalog entries most relevant to
    ``question`` (at most ~6,000 chars).

    Direct matches come first: keyword-level matches that explain part of the question in the
    asked-about economy (or a world benchmark), the clauses of a compound question taking turns
    (:func:`search_catalog_scored`).  Entries of the same economy and theme follow under their
    own heading: up to eight beside fewer than six direct matches, else four; never another
    economy's series or unrelated US headline series.  When no entry answers the question
    strongly (:class:`CatalogHit`), a final line tells the planner to search with English
    concept terms; when only some clauses of a compound question are answered, the line names
    the others.  Keyed usgov modules (EIA, BEA) appear only when ``env`` (default
    ``os.environ``) holds their key.
    """
    limit = max(1, int(limit))
    header = ["OFFICIAL DATA PROVIDERS (series id = provider:native id; data_search finds ids, "
              "data_get fetches a citable series):"]
    for pid, meta in PROVIDERS.items():
        role = meta["role"]
        if pid == "usgov":
            role += "".join(f"; {text}" for key, text in _KEYED_ROLES.items() if _env_value(env, key))
        header.append(f"- {pid}: {meta['name']} — {role}. Example: {meta['example']}")
    header.append("Any FRED series id also works as fred:<ID>; BIS, IMF, World Bank and usgov ids must come "
                  "from this list or data_search.")
    ranking = _ranking(question, None, env)
    whole = ranking.parts[0].query if ranking.parts else _parse_query(question)
    picked = [match.hit.entry for match in ranking.matches if match.direct][:limit]
    beside = _DIGEST_RELATED_MAX if len(picked) < _DIGEST_MIN_PICKS else _DIGEST_RELATED_BESIDE
    related = _related(whole, {entry.series for entry in picked}, env, min(limit - len(picked), beside))
    if _env_value(env, "FRED_API_KEY"):
        scope = "FRED search covers about 800,000 series and World Bank Data360 search its indicators"
    else:
        scope = ("FRED search needs FRED_API_KEY, so search covers this catalog and World Bank Data360 "
                 "only; any known FRED id still fetches as fred:<ID>")
    footer: list[str] = []
    unanswered = [part.text for part, answered in zip(ranking.parts[1:], ranking.answered[1:]) if not answered]
    if not any(ranking.answered):
        footer = ["", "No catalog series answers this question directly: search with short English concept "
                      f"terms (for example \"semiconductor shipments\", \"electricity retail sales\"); {scope}."]
    elif unanswered:
        named = "; ".join(f"\"{_clip(text, _DIGEST_CLAUSE_MAX)}\"" for text in unanswered)
        footer = ["", f"No catalog series answers part of this question directly ({named}): search that part with "
                      f"short English concept terms; {scope}."]
    sections = [("CATALOG SERIES (id — title (units, frequency, seasonal adjustment, geography)):", picked),
                ("RELATED SERIES (same economy or theme; not a direct match):", related)]
    lines = list(header)
    budget = _DIGEST_MAX_CHARS - len("\n".join(footer)) - (1 if footer else 0)
    for title, entries in sections:
        rows = [_digest_line(entry) for entry in entries]
        while rows and len("\n".join(lines + ["", title] + rows)) > budget:
            rows.pop()
        if rows:
            lines += ["", title] + rows
    return "\n".join(lines + footer)


def _cell(text: str, limit: int | None = None) -> str:
    value = " ".join(str(text).split()).replace("|", "\\|")
    return _clip(value, limit) if limit else value


_REFERENCE_DIR = Path(__file__).resolve().parent / "skills" / "data-sources" / "references"
REFERENCE_INDEX = "series-catalog.md"
_PROVIDER_FILES: dict[str, str] = {pid: f"catalog-{pid}.md" for pid in PROVIDERS}
_GENERATED_NOTE = ("Generated from `deerflow_bridge/data_catalog.py` by `render_catalog_files()`; do not edit by "
                   "hand (regenerate with `python deerflow_bridge/data_catalog.py --write-markdown`).")


def _entry_notes(entry: CatalogEntry) -> str:
    extra = []
    if entry.preferred and entry.preferred not in entry.notes:
        extra.append(f"Faster equivalent: {entry.preferred}.")
    if entry.fred_equivalent and entry.fred_equivalent not in entry.notes:
        extra.append(f"FRED mirror: {entry.fred_equivalent}.")
    if entry.requires_key:
        extra.append(f"Needs {entry.requires_key}.")
    return " ".join([entry.notes, *extra]).strip()


def _provider_page(pid: str) -> str:
    meta = PROVIDERS[pid]
    entries = [entry for entry in CATALOG if entry.provider == pid]
    out = [f"# {pid} — {meta['name']}", "", _GENERATED_NOTE, "",
           f"{len(entries)} curated series. Use for: {meta['role']}. Id grammar, column legend and the other "
           f"providers: [{REFERENCE_INDEX}]({REFERENCE_INDEX}).", "",
           "| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |", "|---|---|---|---|---|---|---|---|"]
    for entry in entries:
        out.append(
            f"| `{entry.series}` | {_cell(entry.title, 140)} | {_cell(entry.title_zh)} | {_cell(entry.units)} "
            f"| {entry.frequency} | {entry.seasonal_adjustment} | {entry.geography} "
            f"| {_cell(_entry_notes(entry), 260)} |")
    if pid == "usgov":
        out += ["", "## Recipes (ids are `usgov:<recipe>[/<parameter>]`)", "",
                "| Recipe | Title | Source tool | Freq | Units | Parameter | Needs | Notes |",
                "|---|---|---|---|---|---|---|---|"]
        for key, recipe in USGOV_RECIPES.items():
            if not recipe["enabled"]:
                continue
            parameter = recipe["param_format"]
            if parameter and recipe["param_examples"]:
                parameter += " e.g. " + ", ".join(f"`{example}`" for example in recipe["param_examples"][:4])
            out.append(
                f"| `{key}` | {_cell(recipe['title'])} | {recipe['tool']} | {recipe['frequency']} "
                f"| {_cell(recipe['units'])} | {_cell(parameter)} | {recipe['requires_key'] or '—'} "
                f"| {_cell(recipe['notes'], 260)} |")
    return "\n".join(out) + "\n"


def _index_page() -> str:
    counts = {pid: sum(1 for entry in CATALOG if entry.provider == pid) for pid in PROVIDERS}
    keyed = sorted({entry.requires_key for entry in CATALOG if entry.requires_key})
    out = [
        "# Official data series catalog",
        "",
        _GENERATED_NOTE,
        "",
        f"{len(CATALOG)} curated series across {len(PROVIDERS)} providers. Every id was verified live on "
        f"{VERIFIED_ON} or, when added later, on the day it was added: the provider returned recent data, and "
        "titles and units come from its own metadata. "
        "Pass an id exactly as written to `data_get`; `data_search` searches this catalog first. Read only the "
        "provider page you need; this index holds the id grammar.",
        "",
        "Columns: Freq D/W/M/Q/A = daily/weekly/monthly/quarterly/annual; SA = seasonally adjusted, "
        "SAAR = seasonally adjusted annual rate, NSA = not seasonally adjusted, blank = not applicable or "
        "not published; Geo = ISO3 code, EMU = euro area, WLD = world or global benchmark. Daily series become "
        "monthly: averages, or end-of-period values for policy targets and debt stocks.",
        "",
        "## Providers",
        "",
        "| Provider | Source | Use for | Example id | Series | Page |",
        "|---|---|---|---|---|---|",
    ]
    for pid, meta in PROVIDERS.items():
        page = _PROVIDER_FILES[pid]
        out.append(f"| {pid} | {_cell(meta['name'])} | {_cell(meta['role'])} | `{meta['example']}` | {counts[pid]} "
                   f"| [{page}]({page}) |")
    out += ["", f"Keyed series ({', '.join(keyed)}): the us-gov server loads the EIA and BEA modules only when the "
                "key is set; without it `data_search` and the planner digest do not list them and `data_get` "
                "reports the provider unavailable. "
                "SEC company facts are not available through the supplied handler.",
            "", "## Id grammar", "",
            "- `fred:<FRED id>` — any FRED series id works, catalog or not.",
            "- `bls:<BLS id>` — catalog ids only in practice (BLS has no search); keyless BLS allows 20 requests "
            "a day, so prefer the FRED mirror named in the notes.",
            "- `wb:<INDICATOR>/<ISO3>` — Data360 databases " + ", ".join(WB_DATABASES) + " only; a `data_search` "
            "hit from another Data360 database is discovery metadata that `data_get` cannot fetch.",
            "- `bis:<FLOW>/<KEY>` and `imf:<FLOW>/<KEY>` — key parts follow the dimension order below.",
            "- `usgov:<recipe>[/<parameter>]` — recipes in [catalog-usgov.md](catalog-usgov.md).",
            "", "### BIS dataflows", "",
            "| Flow | Version | Key dimensions (in order) | Citation topic | Title |", "|---|---|---|---|---|"]
    for flow, meta in BIS_FLOWS.items():
        out.append(f"| {flow} | {meta['version']} | {'.'.join(meta['dims'])} | {meta['topic']} | {meta['title']} |")
    out += ["", "### IMF dataflows", "",
            "| Flow | Agency | Key dimensions (in order) | Title |", "|---|---|---|---|"]
    for flow, meta in IMF_FLOWS.items():
        out.append(f"| {flow} | {meta['agency']} | {'.'.join(meta['dims'])} | {meta['title']} |")
    out += ["", "WEO vintages follow `WEO_<YYYY>_<APR|OCT>_VINTAGE` with the WEO key layout.",
            "", "### usgov recipes", "", "| Recipe | Parameter | Freq | Needs |", "|---|---|---|---|"]
    for key, recipe in USGOV_RECIPES.items():
        if recipe["enabled"]:
            out.append(f"| `{key}` | {_cell(recipe['param_format']) or '—'} | {recipe['frequency']} "
                       f"| {recipe['requires_key'] or '—'} |")
    return "\n".join(out) + "\n"


def render_catalog_files() -> dict[str, str]:
    """``{file name: markdown}`` for ``skills/data-sources/references/``: the index
    (``series-catalog.md``: providers, id grammar, flows, recipes) and one page per provider."""
    files = {REFERENCE_INDEX: _index_page()}
    files.update({name: _provider_page(pid) for pid, name in _PROVIDER_FILES.items()})
    return files


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["--write-markdown"] or len(args) > 2:
        print("usage: data_catalog.py --write-markdown [DIRECTORY]", file=sys.stderr)
        return 2
    target = Path(args[1]) if len(args) == 2 else _REFERENCE_DIR
    if not target.is_dir():
        print(f"error: directory does not exist: {target}", file=sys.stderr)
        return 1
    files = render_catalog_files()
    for name, text in files.items():
        (target / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(files)} files to {target} ({len(CATALOG)} series)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
