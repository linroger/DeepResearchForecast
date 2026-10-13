"""Offline tests for deerflow_bridge/data_catalog.py (curated official-data catalog).

Covers catalog integrity (ids, grammar, citation pages, units, policies), the verified
native unit pins replayed against REAL captured provider rows, usgov recipe shapes
replayed against REAL captured EIA / BEA / Treasury responses, EN/ZH search ranking,
the planner digest, and the generated skill reference files.

Same import pattern as test_research_gateway.py: the bridge directory is put on
sys.path and the module is imported by bare name.  Zero network.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_catalog as catalog  # noqa: E402

REAL = Path(__file__).resolve().parent / "fixtures" / "data_sources" / "real"
NATIVE_UNITS = json.loads((REAL / "catalog-native-units-2026-10-12.json").read_text(encoding="utf-8"))
USGOV_CAPTURE = json.loads((REAL / "catalog-usgov-recipes-2026-10-12.json").read_text(encoding="utf-8"))
SKILL_DIR = Path(_BRIDGE_DIR) / "skills" / "data-sources"
NO_KEYS: dict[str, str] = {}
ALL_KEYS = {"FRED_API_KEY": "k", "EIA_API_KEY": "k", "BEA_API_KEY": "k"}
CJK = re.compile(r"[㐀-鿿]")


def _entry(series: str) -> catalog.CatalogEntry:
    entry = catalog.lookup(series)
    assert entry is not None, series
    return entry


def _ids(hits) -> list[str]:
    return [hit.entry.series for hit in hits]


# =============================================================== integrity

def test_ids_are_unique_and_follow_the_provider_grammar():
    ids = [entry.series for entry in catalog.CATALOG]
    assert len(ids) == len(set(ids)) == len({sid.casefold() for sid in ids})
    for entry in catalog.CATALOG:
        native = entry.native
        assert entry.provider in catalog.PROVIDERS
        assert catalog.lookup(entry.series) is entry
        if entry.provider == "fred":
            assert re.fullmatch(r"[A-Z0-9_]+", native)
        elif entry.provider == "bls":
            assert re.fullmatch(r"[A-Z0-9]+", native)
        elif entry.provider == "bis":
            flow, key = native.split("/")
            assert len(key.split(".")) == len(catalog.BIS_FLOWS[flow]["dims"])
        elif entry.provider == "imf":
            flow, key = native.split("/")
            assert len(key.split(".")) == len(catalog.imf_flow_info(flow)["dims"])
        elif entry.provider == "wb":
            indicator, iso3 = native.split("/")
            assert catalog.wb_database(indicator) in catalog.WB_DATABASES and re.fullmatch(r"[A-Z]{3}", iso3)
        else:
            resolved = catalog.resolve_usgov_recipe(native)
            assert resolved is not None and resolved[1]["enabled"], entry.series


def test_metadata_is_complete_and_valid():
    for entry in catalog.CATALOG:
        assert entry.title.strip() and entry.units.strip(), entry.series
        assert CJK.search(entry.title_zh), entry.series
        assert entry.frequency in catalog.FREQUENCIES
        assert entry.seasonal_adjustment in catalog.SEASONAL_ADJUSTMENTS
        assert entry.geography in catalog.GEOGRAPHIES, entry.series
        assert entry.topics and set(entry.topics) <= set(catalog.TOPICS), entry.series
        assert entry.keywords and all(k == " ".join(k.lower().split()) for k in entry.keywords)
        assert entry.aggregation in catalog.AGGREGATIONS
        assert entry.status_policy in catalog.STATUS_POLICIES
        assert not entry.min_start or re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry.min_start)
        assert hash(entry) == hash(entry)  # read-only native_dims never breaks hashing


def test_citation_pages_follow_the_provider_patterns():
    for entry in catalog.CATALOG:
        url, native = entry.source_url, entry.native
        if entry.provider == "fred":
            assert url == f"https://fred.stlouisfed.org/series/{native}"
        elif entry.provider == "bls":
            assert url == f"https://data.bls.gov/timeseries/{native}"
        elif entry.provider == "bis":
            flow, key = native.split("/")
            meta = catalog.BIS_FLOWS[flow]
            assert url == f"https://data.bis.org/topics/{meta['topic']}/BIS,{flow},{meta['version']}/{key}"
        elif entry.provider == "imf":
            meta = catalog.imf_flow_info(native.split("/")[0])
            assert url == f"https://data.imf.org/en/datasets/{meta['agency']}:{meta['base_flow']}"
        elif entry.provider == "wb":
            assert url == f"https://data360.worldbank.org/en/indicator/{native.split('/')[0]}"
        else:
            assert url == catalog.resolve_usgov_recipe(native)[1]["source_url"] and url.startswith("https://")


def test_daily_series_name_their_monthly_aggregation():
    for entry in catalog.CATALOG:
        if entry.frequency == "D":
            assert entry.aggregation in ("avg", "eop"), entry.series
    for sid in ("fred:DFEDTARU", "fred:DFEDTARL", "fred:WALCL", "usgov:treasury/debt_to_penny",
                "usgov:treasury/debt_held_public"):
        assert _entry(sid).aggregation == "eop", sid
    for sid in ("fred:DGS10", "fred:DCOILBRENTEU", "fred:DFF", "fred:SOFR", "fred:NASDAQSOX", "fred:DEXCHUS"):
        assert _entry(sid).aggregation == "avg", sid


def test_status_policies_follow_the_publisher():
    for entry in catalog.CATALOG:
        if entry.provider == "wb":
            expected = {"WB_WDI": "history_only", "IMF_WEO": "weo_vintage", "WB_GEP": "gep_vintage"}
            assert entry.status_policy == expected[catalog.wb_database(entry.native.split("/")[0])]
        elif entry.provider == "imf" and entry.native.startswith("WEO"):
            assert entry.status_policy == "weo_vintage", entry.series
        else:
            assert entry.status_policy == "", entry.series


def test_route_links_point_at_verified_catalog_ids():
    for entry in catalog.CATALOG:
        if entry.preferred:
            fast = _entry(entry.preferred)
            assert fast.series != entry.series and fast.frequency == entry.frequency
            assert fast.geography == entry.geography or "WLD" in (fast.geography, entry.geography)
        if entry.fred_equivalent:
            assert entry.provider == "bls" and re.fullmatch(r"fred:[A-Z0-9]+", entry.fred_equivalent)
    pairs = {"bls:LNS14000000": "fred:UNRATE", "bls:CES0000000001": "fred:PAYEMS", "bls:CUSR0000SA0": "fred:CPIAUCSL",
             "bls:CUSR0000SA0L1E": "fred:CPILFESL", "bls:JTS000000000000000JOL": "fred:JTSJOL",
             "bls:CES0500000003": "fred:CES0500000003", "bls:CUUR0000SA0": "fred:CPIAUCNS"}
    for bls, fred in pairs.items():
        assert _entry(bls).fred_equivalent == fred
    assert _entry("bls:CUSR0000SAM").fred_equivalent == ""  # FRED has no such series
    assert _entry("imf:PCPS/G001.PCOPP.USD.M").preferred == "fred:PCOPPUSDM"
    assert _entry("imf:WEO/USA.NGDP_RPCH.A").preferred == "wb:IMF_WEO_NGDP_RPCH/USA"
    assert _entry("usgov:spending/total").min_start == "2007-10-01"


def test_curated_units_follow_the_verified_meaning():
    assert _entry("wb:IMF_WEO_NGDPD/USA").units == "U.S. dollars"  # whole dollars despite UNIT_MULT 9
    assert _entry("wb:IMF_WEO_NGDPD/USA").native_unit == ("USD", 9)
    assert _entry("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN").units == "Percent change per annum"
    assert _entry("wb:WB_WDI_FP_CPI_TOTL_ZG/IND").units == "Percent change per annum"
    assert _entry("bis:WS_CREDIT_GAP/Q.US.P.A.C").units == "Percentage points of GDP"
    assert _entry("wb:IMF_WEO_LUR/USA").units == "Percent of labor force"
    assert _entry("wb:WB_WDI_EG_USE_ELEC_KH_PC/USA").units == "Kilowatt-hours per capita"


def test_every_wb_and_bis_entry_carries_a_native_unit_pin():
    for entry in catalog.CATALOG:
        if entry.provider in ("wb", "bis"):
            code, mult = entry.native_unit
            assert isinstance(code, str) and isinstance(mult, int), entry.series
        else:
            assert entry.native_unit is None and not entry.native_dims, entry.series
    assert dict(_entry("bis:WS_TC/Q.US.P.A.M.770.A").native_dims) == {"UNIT_TYPE": "770"}
    assert dict(_entry("bis:WS_XRU/M.JP.JPY.A").native_dims) == {"CURRENCY": "JPY", "COLLECTION": "A"}
    assert dict(_entry("bis:WS_CBTA/M.CN.B.XDC.CNY.N").native_dims) == {"CURRENCY": "CNY"}
    assert dict(_entry("wb:IMF_WEO_NGDP_RPCH/CHN").native_dims) == {"COMP_BREAKDOWN_1": "V_LST"}
    with pytest.raises(TypeError):
        _entry("bis:WS_TC/Q.US.P.A.M.770.A").native_dims["UNIT_TYPE"] = "771"  # read-only


def _single(values: list[str], default: str) -> str:
    assert len(values) <= 1, values
    return values[0] if values else default


@pytest.mark.parametrize("provider", ["wb", "bis"])
def test_native_unit_pins_replay_the_real_captured_rows(provider):
    captured = NATIVE_UNITS[provider]
    entries = [entry for entry in catalog.CATALOG if entry.provider == provider]
    assert {entry.series for entry in entries} == set(captured), "every pinned entry needs a live capture"
    for entry in entries:
        row = captured[entry.series]
        code = _single(row["UNIT_MEASURE"], "")
        mult = int(_single(row["UNIT_MULT"], "0"))  # SDMX: an absent UNIT_MULT means units (0)
        assert entry.native_unit == (code, mult), entry.series
        for dim, value in entry.native_dims.items():
            assert row["dims"][dim] == [value], (entry.series, dim)


def test_curated_units_never_copy_a_misleading_native_label():
    rows = NATIVE_UNITS["wb"]
    assert rows["wb:IMF_WEO_LUR/USA"]["UNIT_MEASURE_NAME"] == ["Percentage of population"]
    assert rows["wb:WB_WDI_EG_USE_ELEC_KH_PC/USA"]["UNIT_MEASURE_NAME"] == ["Kilowatt hour (KWh)"]
    assert rows["wb:IMF_WEO_NGDPD/USA"]["UNIT_MEASURE_NAME"] == ["billion US Dollars"]
    for series, row in rows.items():
        assert _entry(series).units not in row["UNIT_MEASURE_NAME"] or _entry(series).units == "Persons"


# =============================================================== usgov recipes

_RECIPE_KEYS = {
    "kind", "title", "title_zh", "tool", "tool_args", "endpoint", "api_url", "fields", "filters", "sort",
    "date_field", "value_field", "period_format", "param_field", "param_facets", "param_format", "param_examples",
    "param_pattern", "tiebreak_field", "facets", "units_field", "native_units", "line_description",
    "max_obs_per_call", "frequency", "seasonal_adjustment", "units", "source_url", "notes", "aggregation",
    "min_start", "requires_key", "enabled",
}


def test_recipes_share_one_shape():
    kinds = {"treasury", "usaspending", "sec", "eia", "bea_nipa", "bea_industry"}
    for key, recipe in catalog.USGOV_RECIPES.items():
        assert set(recipe) == _RECIPE_KEYS, key
        assert recipe["kind"] in kinds and recipe["frequency"] in catalog.FREQUENCIES
        assert isinstance(recipe["tool_args"], dict) and isinstance(recipe["facets"], dict)
        assert isinstance(recipe["param_examples"], tuple) and isinstance(recipe["param_facets"], tuple)
        assert recipe["aggregation"] in catalog.AGGREGATIONS and recipe["title"] and CJK.search(recipe["title_zh"])
        assert "key" not in recipe["api_url"].lower() and recipe["source_url"].startswith("https://")
        assert recipe["requires_key"] == {"eia": "EIA_API_KEY", "bea_nipa": "BEA_API_KEY",
                                          "bea_industry": "BEA_API_KEY"}.get(recipe["kind"], ""), key
        for example in recipe["param_examples"]:
            assert catalog.resolve_usgov_recipe(f"{key}/{example}") == (key, recipe, example)
        if recipe["param_facets"]:
            assert recipe["param_format"].count(".") == len(recipe["param_facets"]) - 1
    assert catalog.USGOV_RECIPES["treasury/mts_customs_duties"]["filters"] == "line_code_nbr:eq:110"
    assert catalog.USGOV_RECIPES["treasury/mts_individual_income_taxes"]["filters"] == "line_code_nbr:eq:20"
    assert catalog.USGOV_RECIPES["treasury/mts_corporation_income_taxes"]["filters"] == "line_code_nbr:eq:30"
    assert catalog.USGOV_RECIPES["treasury/mts_interest_gross"]["filters"] == "line_code_nbr:eq:360"
    assert catalog.USGOV_RECIPES["spending/total"]["min_start"] == "2007-10-01"


def test_recipe_parameters_are_validated():
    assert catalog.resolve_usgov_recipe("eia/electricity_sales/VA.COM")[2] == "VA.COM"
    assert catalog.resolve_usgov_recipe("EIA/Electricity_Sales/TX.IND")[0] == "eia/electricity_sales"
    for bad in ("eia/electricity_sales/VA", "eia/electricity_sales/VA.XYZ", "eia/electricity_sales",
                "eia/net_generation/ZZZ", "eia/crude_production/US", "bea/value_added_by_industry/x",
                "sec/AAPL", "sec/AAPL/", "treasury/fx", "treasury/debt_to_penny/x"):
        assert catalog.resolve_usgov_recipe(bad) is None, bad
    assert catalog.resolve_usgov_recipe("sec/AAPL/Revenues")[0] == "sec"


def test_sec_and_keyed_recipes_are_advertised_only_when_servable():
    sec = catalog.USGOV_RECIPES["sec"]
    assert not catalog.recipe_available(sec, env=ALL_KEYS)
    eia = catalog.USGOV_RECIPES["eia/electricity_sales"]
    assert not catalog.recipe_available(eia, env=NO_KEYS)
    assert not catalog.recipe_available(eia, env={"EIA_API_KEY": "  "})
    assert catalog.recipe_available(eia, env={"EIA_API_KEY": "k"})
    assert catalog.recipe_available(catalog.USGOV_RECIPES["treasury/mts_deficit"], env=NO_KEYS)
    entry = _entry("usgov:eia/generating_capacity/BAT")
    assert entry.requires_key == "EIA_API_KEY" and not catalog.entry_available(entry, env=NO_KEYS)
    assert not any(e.series.startswith("usgov:sec") for e in catalog.CATALOG)
    assert "SEC" not in catalog.PROVIDERS["usgov"]["role"]
    usgov_page = catalog.render_catalog_files()["catalog-usgov.md"]
    assert "`sec`" not in usgov_page and "companyconcept" not in usgov_page


def _eia_args(recipe: dict, param: str, captured_args: dict) -> dict:
    facets = dict(recipe["facets"])
    if recipe["param_facets"]:
        facets.update(zip(recipe["param_facets"], param.split(".")))
    return {**recipe["tool_args"], "facets": "; ".join(f"{k}={v}" for k, v in facets.items()),
            "start": captured_args["start"], "length": captured_args["length"]}


def test_usgov_recipes_replay_the_real_captured_responses():
    entries = [e for e in catalog.CATALOG if e.provider == "usgov"
               and (e.requires_key or e.native.startswith("treasury/mts_"))]
    assert {e.series for e in entries} == set(USGOV_CAPTURE["series"]), "every new recipe entry needs a capture"
    for entry in entries:
        key, recipe, param = catalog.resolve_usgov_recipe(entry.native)
        row = USGOV_CAPTURE["series"][entry.series]
        if recipe["kind"] == "eia":
            assert row["args"] == _eia_args(recipe, param, row["args"]), entry.series
            assert row["units"] == [recipe["native_units"]], entry.series
            columns = row["columns"]
            assert {recipe["date_field"], recipe["value_field"], recipe["units_field"]} <= set(columns)
            first = dict(zip(columns, row["first"]))
            for pin in row["args"]["facets"].split("; "):
                facet, value = pin.split("=")
                assert str(first[facet]) == value, (entry.series, facet)
            pattern = r"\d{4}-\d{2}" if recipe["period_format"] == "YYYY-MM" else r"\d{4}"
            assert re.fullmatch(pattern, first[recipe["date_field"]])
            assert isinstance(first[recipe["value_field"]], (int, float))
        elif recipe["kind"] == "bea_nipa":
            assert row["args"] == {**recipe["tool_args"], "year": row["args"]["year"]}
            assert row["n_match"] == 1, entry.series  # exactly one table line carries the description
            assert 0 < len(row["observations"]) <= recipe["max_obs_per_call"]
            assert all(re.fullmatch(r"\d{4}Q[1-4]", obs["period"]) for obs in row["observations"])
        elif recipe["kind"] == "bea_industry":
            assert row["args"] == {**recipe["tool_args"], recipe["param_field"]: param, "year": row["args"]["year"]}
            assert row["n_rows"] == 1 and 0 < len(row["observations"]) <= recipe["max_obs_per_call"]
            assert all(re.fullmatch(r"\d{4}Q(?:I|II|III|IV)", obs["period"]) for obs in row["observations"])
        else:
            line = recipe["filters"].split(":eq:")[1]
            assert row["args"]["endpoint"] == recipe["endpoint"] and row["args"]["fields"] == recipe["fields"]
            assert row["rows"] and {r["line_code_nbr"] for r in row["rows"]} == {line}
            assert len({r["classification_desc"] for r in row["rows"]}) == 1
            assert set(row["rows"][0]) == set(recipe["fields"].split(","))


# =============================================================== search

def test_cjk_numerals_normalize_period_words():
    assert catalog._cjk_numerals("美国十年期国债") == "美国10年期国债"
    assert catalog._cjk_numerals("两年期") == "2年期"
    assert catalog._cjk_numerals("三十年期国债") == "30年期国债"
    assert catalog._cjk_numerals("三个月") == "3个月"
    assert catalog._cjk_numerals("二〇二五年") == "2025年"
    assert catalog._cjk_numerals("统一大市场") == "统一大市场"


def test_zh_tenor_queries_rank_the_matching_treasury_maturity_first():
    ten = catalog.search_catalog_scored("美国十年期国债收益率", env=NO_KEYS)
    # Strong matches lead (the 10-year TIPS yield is a 10-year Treasury yield too); the 2-year is weak.
    assert _ids(ten)[:3] == ["fred:DGS10", "fred:DFII10", "fred:DGS2"]
    assert [hit.strong for hit in ten[:3]] == [True, True, False]
    two = catalog.search_catalog_scored("美国两年期国债收益率", env=NO_KEYS)
    assert _ids(two)[0] == "fred:DGS2" and two[0].strong
    english = catalog.search_catalog_scored("US 10-year treasury yield", env=NO_KEYS)
    assert _ids(english)[0] == "fred:DGS10" and not [h for h in english if h.entry.series == "fred:DGS2"][0].strong


def test_zh_electricity_demand_finds_electricity_series():
    hits = catalog.search_catalog_scored("电力需求", env=NO_KEYS)
    assert hits[0].entry.series.startswith("wb:WB_WDI_EG_USE_ELEC_KH_PC/") and hits[0].strong
    keyed = catalog.search_catalog("用电量", env=ALL_KEYS)
    assert any(entry.series.startswith("usgov:eia/electricity_sales/") for entry in keyed)


def test_partial_concept_matches_are_weak_so_live_search_runs():
    zh = catalog.search_catalog_scored("半导体出口", env=NO_KEYS)
    assert zh[0].entry.series == "fred:IPG3344S" and _ids(zh).index("fred:IPG3344S") < _ids(zh).index("fred:EXPGSC1")
    assert not any(hit.strong for hit in zh)
    en = catalog.search_catalog_scored("semiconductor exports", env=NO_KEYS)
    assert not any(hit.strong for hit in en)
    semis = catalog.search_catalog_scored("semiconductor", env=NO_KEYS)
    assert semis[0].entry.series == "fred:IPG3344S" and semis[0].strong
    assert catalog.search_catalog_scored("fred:UNRATE", env=NO_KEYS)[0].strong


def test_strong_hits_require_coverage_and_geography():
    china = catalog.search_catalog_scored("Will China cut its policy rate below 1% in 2027?", env=NO_KEYS)
    assert china[0].entry.series == "bis:WS_CBPOL/M.CN" and china[0].strong
    assert not [hit for hit in china if hit.entry.series == "bis:WS_CBPOL/M.US"][0].strong
    tariffs = catalog.search_catalog_scored("US customs duties FY2026", env=NO_KEYS)
    assert tariffs[0].entry.series == "usgov:treasury/mts_customs_duties" and tariffs[0].strong
    assert catalog.STRONG_CONCEPT_SCORE == 4.0


def test_iso3_geographies_resolve_to_the_named_economy():
    assert _ids(catalog.search_catalog_scored("policy rate CHN", env=NO_KEYS))[0] == "bis:WS_CBPOL/M.CN"
    assert catalog.search_catalog("inflation JPN", env=NO_KEYS)[0].geography == "JPN"
    assert catalog.search_catalog("unemployment rate EMU", env=NO_KEYS)[0].geography == "EMU"
    assert catalog.query_geographies("EA inflation") == {"EMU"}
    for query in ("fedex shipping volumes", "urban population growth", "silicon carbide wafer exports",
                  "electricity usage per capita", "can the economy grow"):
        assert catalog.query_geographies(query) == frozenset(), query


def test_fast_routes_rank_ahead_of_the_slow_equivalent():
    copper = catalog.search_catalog("copper price", env=NO_KEYS)
    assert [e.series for e in copper[:2]] == ["fred:PCOPPUSDM", "imf:PCPS/G001.PCOPP.USD.M"]
    gdp = catalog.search_catalog("real gdp growth national accounts", env=ALL_KEYS, limit=20)
    ids = [e.series for e in gdp]
    assert ids.index("fred:A191RL1Q225SBEA") < ids.index("usgov:bea/real_gdp_growth")


def test_keyed_entries_follow_the_environment():
    query = "US battery storage capacity"
    assert not any(e.series.startswith("usgov:eia/") for e in catalog.search_catalog(query, env=NO_KEYS, limit=50))
    assert catalog.search_catalog(query, env={"EIA_API_KEY": "k"})[0].series == "usgov:eia/generating_capacity/BAT"
    assert catalog.lookup("usgov:eia/generating_capacity/BAT") is not None  # lookup ignores availability


def test_new_breadth_series_are_found_in_english_and_chinese():
    cases = {
        "semiconductor production": "fred:IPG3344S", "芯片产量": "fred:IPG3344S",
        "philadelphia semiconductor index": "fred:NASDAQSOX", "imports from China": "fred:IMPCH",
        "tariff revenue": "usgov:treasury/mts_customs_duties", "关税收入": "usgov:treasury/mts_customs_duties",
        "corporate income taxes": "usgov:treasury/mts_corporation_income_taxes",
        "interest on the debt": "usgov:treasury/mts_interest_gross",
    }
    for query, expected in cases.items():
        assert catalog.search_catalog(query, env=NO_KEYS)[0].series == expected, query
    keyed = {"data center electricity": "usgov:eia/electricity_sales/US.COM", "储能装机": "usgov:eia/generating_capacity/BAT",
             "solar generation": "usgov:eia/net_generation/SUN", "数据中心": "usgov:bea/value_added_by_industry/514"}
    for query, expected in keyed.items():
        assert expected in [e.series for e in catalog.search_catalog(query, env=ALL_KEYS, limit=3)], query


def test_english_query_translates_zh_concepts_for_provider_search():
    assert catalog.english_query("中国半导体出口") == "China semiconductor exports"
    assert catalog.english_query("美国十年期国债收益率") == "United States 10 year treasury yield"
    assert catalog.english_query("美联储降息") == "Federal Reserve rate cut"
    assert catalog.english_query("  semiconductor shipments ") == "semiconductor shipments"
    assert catalog.english_query("") == ""


_CPI_FED = ("Will US CPI inflation fall below 2.5% year over year by December 2027, and how will the Federal "
            "Reserve policy rate evolve through 2027?")
_US_POLICY_RATE = {"fred:FEDFUNDS", "fred:DFEDTARU", "bis:WS_CBPOL/M.US"}


def test_movement_verbs_dates_and_units_are_not_concept_terms():
    # "evolve", "through", "December", "where" and "TWh" name nothing a series measures.
    fed = catalog.search_catalog_scored("How will the Federal Reserve policy rate evolve through December 2027?",
                                        env=NO_KEYS)
    assert set(_ids(fed)[:3]) == _US_POLICY_RATE and all(hit.strong and hit.coverage == 1.0 for hit in fed[:3])
    euro = catalog.search_catalog_scored("Where will the euro-area policy rate be at the end of 2026?", env=NO_KEYS)
    assert euro[0].entry.series == "bis:WS_CBPOL/M.XM" and euro[0].strong
    # Only the euro area's policy rates answer: BIS's series and the ECB deposit facility rate.
    assert {hit.entry.series for hit in euro if hit.strong} == {"bis:WS_CBPOL/M.XM", "fred:ECBDFR"}
    zh = catalog.search_catalog_scored("美联储利率将如何变化？", env=NO_KEYS)
    assert zh[0].entry.series == "fred:FEDFUNDS" and zh[0].strong
    # A modifier that is otherwise a stopword stays part of the concept: "data" of "data center"
    # keeps US electricity per capita from answering a data-center question on its own.
    for query in ("US data center electricity demand",
                  "Will US data-center electricity demand exceed 500 TWh by 2030?"):
        keyless = catalog.search_catalog_scored(query, env=NO_KEYS)
        assert keyless[0].entry.series == "wb:WB_WDI_EG_USE_ELEC_KH_PC/USA", query
        assert not any(hit.strong for hit in keyless), query
        keyed = catalog.search_catalog_scored(query, env=ALL_KEYS)
        assert keyed[0].entry.series == "usgov:eia/electricity_sales/US.COM" and keyed[0].strong, query
    # ...while the generic head of "exchange rate" stays generic.
    yuan = catalog.search_catalog_scored("Will the yuan exchange rate exceed 7.5 per dollar by 2027?", env=NO_KEYS)
    assert _ids(yuan)[0] == "fred:DEXCHUS" and yuan[0].strong


def test_compound_questions_rank_every_clause():
    hits = catalog.search_catalog_scored(_CPI_FED, env=NO_KEYS)
    strong = {hit.entry.series for hit in hits if hit.strong}
    assert _US_POLICY_RATE | {"fred:CPIAUCSL", "wb:IMF_WEO_PCPIPCH/USA"} <= strong
    # The clauses take turns at the top (question order): a CPI series, then a policy rate.
    assert _ids(hits)[:4] == ["wb:IMF_WEO_PCPIPCH/USA", "bis:WS_CBPOL/M.US", "fred:CPIAUCSL", "fred:FEDFUNDS"]
    assert all(hit.entry.geography == "USA" for hit in hits)
    jobs = catalog.search_catalog_scored(
        "Will the US unemployment rate exceed 4.5% by the end of 2027, and how will the Fed policy rate respond?",
        env=NO_KEYS)
    assert _ids(jobs)[:2] == ["fred:UNRATE", "bis:WS_CBPOL/M.US"] and jobs[0].strong and jobs[1].strong
    # A clause naming no economy inherits the question's: only the US policy rate answers it.
    inherited = catalog.search_catalog_scored(
        "Will US CPI inflation exceed 3% in 2027, and where will the policy rate be?", env=NO_KEYS, limit=50)
    rates = {hit.entry.series for hit in inherited if hit.strong and hit.entry.series.startswith("bis:WS_CBPOL/")}
    assert rates == {"bis:WS_CBPOL/M.US"}
    zh = catalog.search_catalog_scored("美国CPI会降到2.5%以下吗？美联储利率将如何变化？", env=NO_KEYS)
    assert {"fred:CPIAUCSL", "fred:FEDFUNDS"} <= {hit.entry.series for hit in zh if hit.strong}
    # Abbreviations and decimals are no clause boundaries; a clause naming no concept is no clause.
    for single in ("Will U.S. CPI inflation exceed 3.5% in 2027?", "Will the Fed cut rates and will China's GDP "
                   "growth exceed 5%?", "US unemployment rate"):
        assert len(catalog._query_parts(single)) == 1, single


# The clause and conjunct splits as first written. They rescanned a whitespace run from every one
# of its positions (DATA-5: 10,000 spaces took 1.2 s); the linear forms must split exactly alike.
_REFERENCE_CLAUSE_RE = re.compile(
    r"(?<!\b[A-Za-z])\.(?=\s|$)|[?!;。？！；：\n]+|:\s|,\s*(?:and|but|or|while|whereas)\s+"
    r"|\s+(?:and|but)\s+(?=(?:how|what|when|where|whether|which|who|why|will|would|could|can|should|does|do"
    r"|did|is|are)\b)"
    r"|[，、]",
    re.IGNORECASE)
_REFERENCE_CONJUNCT_RE = re.compile(r"\s+(?:and|or)\s+|\s+&\s+", re.IGNORECASE)
_SPLIT_WORDS = ("and", "AND", "but", "or", "Or", "while", "whereas", "how", "will", "what", "is", "do", "cpi",
                "inflation", "US", "U.S.", "unemployment", "rate", "China", "GDP", "oil price", "Fed", "&", ",",
                ":", ".", "?", "!", ";", "。", "，", "、", "：", "？", "通胀", "美国", "a.", "order", "andhow",
                "credit spread", "2.5%", "2027", "fred:UNRATE", "S.")
_SPLIT_SPACES = (" ", "\n", "\t", "\r", "　", "\xa0", "\x0b", "  ", "\n\n", " \n", "\n ", "\r\n")


def _reference_clause_texts(query: str) -> list[str]:
    """_query_parts' clause texts under the reference split."""
    texts: list[str] = []
    seen: set[str] = set()
    for piece in _REFERENCE_CLAUSE_RE.split(query):
        text = " ".join(piece.split())
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        parsed = catalog._parse_query(text)
        if parsed.concept_words or parsed.concept_chars:
            texts.append(text)
    return texts[:catalog._MAX_CLAUSES] if len(texts) >= 2 else []


def test_clause_and_conjunct_splits_are_linear_and_split_as_before():
    rng = random.Random(20261014)
    for _ in range(2000):
        query = "".join(rng.choice(_SPLIT_WORDS) if rng.random() < 0.5
                        else "".join(rng.choice(_SPLIT_SPACES) for _ in range(rng.randint(1, 4)))
                        for _ in range(rng.randint(0, 14)))
        assert [part.text for part in catalog._query_parts(query)[1:]] == _reference_clause_texts(query), repr(query)
        assert catalog._CONJUNCT_RE.split(query) == _REFERENCE_CONJUNCT_RE.split(query), repr(query)
    # Long whitespace runs (before: about 30 s each at this length) now cost one pass.
    for query in (" " * 50_000 + "x", "\n " * 25_000 + "x", "cpi" + " " * 50_000 + "and inflation",
                  ":" + " " * 50_000 + "and how will the Fed respond"):
        started = time.perf_counter()
        catalog.search_catalog_scored(query, env=NO_KEYS)
        assert time.perf_counter() - started < 2.0, repr(query[:12])


# =============================================================== geographies, publishers, measures

AGENT_USAGE = json.loads((REAL / "agent_usage" / "carriers-2026-10-13.json").read_text(encoding="utf-8"))


def test_every_geography_name_reads_back_as_its_own_code():
    names = [name for name, _aliases in catalog.GEOGRAPHIES.values()]
    assert len(names) == len(set(names))
    for code, (name, aliases) in catalog.GEOGRAPHIES.items():
        zh = next(alias for alias in aliases if CJK.search(alias))
        assert name.casefold() in aliases, code  # the English name is an alias (label round trip)
        assert catalog.query_geographies(name) == {code}, code
        assert catalog.query_geographies(zh) == {code}, code
        assert catalog.query_geographies(f"policy rate {code}") == {code}, code
        assert not any("bank" in alias.split() for alias in aliases), code
    for code in ("VNM", "IDN", "MEX", "BRA", "TUR", "SAU", "ZAF", "KOR", "AUS", "CAN", "RUS", "ARG", "THA", "MYS",
                 "PHL", "PAK", "BGD", "EGY", "NGA", "POL", "NLD", "ESP", "ITA", "FRA", "CHE", "SWE", "SGP", "TWN",
                 "HKG"):
        assert code in catalog.GEOGRAPHIES, code


def test_the_longest_geography_alias_wins():
    assert catalog.query_geographies("中国香港GDP增速") == {"HKG"}
    assert catalog.query_geographies("印度尼西亚出口") == {"IDN"}
    assert catalog.query_geographies("Taiwan, China semiconductor exports") == {"TWN"}
    assert catalog.query_geographies("China and Taiwan chip exports") == {"CHN", "TWN"}
    assert catalog.query_geographies("Will Vietnam or Indonesia grow faster?") == {"VNM", "IDN"}
    assert catalog.query_geographies("Turkish inflation") == {"TUR"}
    # A demonym of a new economy is no concept word: the Data360 search keeps the topic terms.
    assert catalog.english_query("越南出口") == "Vietnam exports"


@pytest.mark.parametrize("publisher", [
    "World Bank", "世界银行", "World Trade Organization", "WTO", "IMF", "International Monetary Fund",
    "国际货币基金组织", "OECD", "经合组织", "United Nations", "UN", "联合国", "BIS", "IMF World Economic Outlook",
    "World Bank Global Economic Prospects", "World Semiconductor Trade Statistics (WSTS)",
])
def test_publishers_name_no_place(publisher):
    assert catalog.query_geographies(f"{publisher} forecast") == frozenset(), publisher
    assert catalog.query_geographies(f"China GDP growth, {publisher} forecast") == {"CHN"}, publisher


def test_a_question_naming_publishers_keeps_its_country():
    question = "2027年中国实际GDP增速会低于4%吗？结合IMF与世界银行预测"
    assert catalog.query_geographies(question) == {"CHN"}
    assert len(catalog._query_parts(question)) == 1  # "结合IMF与世界银行预测" names no statistic
    assert "fx" not in catalog._parse_query("国际货币基金组织预测中国经济增速").topics  # 货币 of the IMF's name
    hits = catalog.search_catalog_scored(question, env=NO_KEYS)
    assert {hit.entry.series for hit in hits if hit.strong} == {
        "wb:IMF_WEO_NGDP_RPCH/CHN", "wb:WB_GEP_NYGDPMKTPKDZ/CHN", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN"}
    # The publisher still selects its own series: the World Bank's GEP leads a World Bank question.
    assert _ids(hits)[0] == "wb:WB_GEP_NYGDPMKTPKDZ/CHN"
    english = catalog.search_catalog_scored("China real GDP growth: IMF and World Bank forecasts", env=NO_KEYS)
    assert {hit.entry.geography for hit in english if hit.strong} == {"CHN"}
    # "world" and "global" still name the world.
    assert catalog.query_geographies("world trade volume") == catalog.query_geographies("global GDP") == {"WLD"}


def test_ecb_deposit_facility_rate_is_curated_and_leads_its_question():
    entry = _entry("fred:ECBDFR")
    ecb = next(row for row in AGENT_USAGE["questions"]["q4_ecb_dfr"]["series"] if row["series"] == "fred:ECBDFR")
    assert (entry.title, entry.units) == (ecb["title"], ecb["units"])
    assert entry.seasonal_adjustment == ecb["seasonal_adjustment"] == "NSA"
    assert ecb["provenance"]["native_frequency"] == entry.frequency == "D"
    assert (entry.geography, entry.aggregation, entry.title_zh) == ("EMU", "eop", "欧洲央行存款便利利率")
    assert {"deposit facility rate", "存款便利利率"} <= set(entry.keywords)
    # BIS's euro-area policy rate is the deposit facility rate only from 18 Sep 2024 (live COMPILATION).
    bis = next(row for row in AGENT_USAGE["questions"]["q4_ecb_dfr"]["series"] if row["series"] == "bis:WS_CBPOL/M.XM")
    compilation = bis["provenance"]["attributes"]["COMPILATION"][0]
    assert compilation.startswith("From 18 Sep 2024 onwards: official central bank steering rate is the deposit")
    assert "from 15 Oct 2008 to 17 Sep 2024: official central bank liquidity providing, main refinancing" in compilation
    note = _entry("bis:WS_CBPOL/M.XM").notes
    assert note.startswith("From 18 Sep 2024 BIS reports the ECB deposit facility rate") and "fred:ECBDFR" in note
    for question in ("What will the euro-area deposit facility rate be at the end of 2026?", "欧元区存款便利利率"):
        hits = catalog.search_catalog_scored(question, env=NO_KEYS)
        assert _ids(hits)[:2] == ["fred:ECBDFR", "bis:WS_CBPOL/M.XM"] and hits[0].strong, question
        assert {hit.entry.series for hit in hits if hit.strong} == {"fred:ECBDFR", "bis:WS_CBPOL/M.XM"}, question
    deposit = catalog.search_catalog_scored("ECB deposit rate", env=NO_KEYS)
    assert [hit.entry.series for hit in deposit if hit.strong] == ["fred:ECBDFR"]
    assert _ids(catalog.search_catalog_scored("US policy rate", env=NO_KEYS, limit=50)).count("fred:ECBDFR") <= 1
    assert not [hit for hit in catalog.search_catalog_scored("US policy rate", env=NO_KEYS, limit=50)
                if hit.entry.series == "fred:ECBDFR" and hit.strong]


@pytest.mark.parametrize("question", [
    "European Central Bank deposit facility rate",
    "Will the European Central Bank deposit facility rate be below 2% in June 2027?",
    "ECB deposit facility rate", "ECB deposit facility", "欧洲央行存款便利利率",
])
def test_deposit_facility_wording_ranks_the_ecb_deposit_rate_first(question):
    # BIS's euro-area rate is the main refinancing rate before 18 Sep 2024, so for the deposit
    # facility rate FRED's daily ECBDFR leads, strong, however the ECB is named.
    hits = catalog.search_catalog_scored(question, env=NO_KEYS)
    assert _ids(hits)[:2] == ["fred:ECBDFR", "bis:WS_CBPOL/M.XM"], question
    assert hits[0].strong and hits[0].score > hits[1].score, question


def test_main_refinancing_wording_still_leads_with_the_bis_euro_area_rate():
    for question in ("European Central Bank main refinancing rate", "ECB main refinancing rate", "欧洲央行主要再融资利率"):
        assert _ids(catalog.search_catalog_scored(question, env=NO_KEYS))[0] == "bis:WS_CBPOL/M.XM", question


_CORE_OR_PCE = re.compile(r"^(?:core|核心)|pce")


def test_headline_inflation_names_the_all_items_cpi_family_only():
    headline = {"headline inflation", "整体通胀"}
    family = set()
    for entry in catalog.CATALOG:
        keywords = set(entry.keywords)
        if any(_CORE_OR_PCE.search(keyword) for keyword in keywords):
            assert not headline & keywords, entry.series
        elif keywords & {"cpi", "consumer prices", "hicp"}:
            assert headline <= keywords, entry.series
            family.add(entry.series)
    assert {"fred:CPIAUCSL", "bls:CUUR0000SA0", "bis:WS_LONG_CPI/M.US.771", "bis:WS_LONG_CPI/M.XM.771",
            "wb:IMF_WEO_PCPIPCH/USA", "imf:CPI/USA.CPI._T.YOY_PCH_PA_PT.M"} <= family
    core = {"fred:CPILFESL", "fred:PCEPILFE", "bls:CUUR0000SA0L1E", "bls:CUSR0000SA0L1E"}
    for question in ("US headline inflation is below 2.5% in December 2027", "美国整体通胀"):
        strong = {hit.entry.series for hit in catalog.search_catalog_scored(question, env=NO_KEYS) if hit.strong}
        assert {"fred:CPIAUCSL", "bls:CUUR0000SA0", "bis:WS_LONG_CPI/M.US.771"} <= strong <= family, question
    for question in ("US core inflation", "美国核心通胀"):
        strong = {hit.entry.series for hit in catalog.search_catalog_scored(question, env=NO_KEYS) if hit.strong}
        assert strong and strong <= core, question
    china = catalog.search_catalog_scored("China headline inflation", env=NO_KEYS)
    assert {hit.entry.geography for hit in china if hit.strong} == {"CHN"}


def test_a_price_question_is_not_answered_by_a_quantity_series():
    keyed = catalog.search_catalog_scored("electricity retail price", env=ALL_KEYS, limit=20)
    strong = [hit.entry.series for hit in keyed if hit.strong]
    assert strong == [f"usgov:eia/electricity_price/US.{sector}" for sector in ("ALL", "COM", "IND", "RES")]
    assert _ids(keyed)[:4] == strong
    assert not any(hit.strong for hit in keyed if "electricity_sales" in hit.entry.series)
    us = catalog.search_catalog_scored("US electricity retail price", env=ALL_KEYS, limit=20)
    assert _ids(us)[0] == "usgov:eia/electricity_price/US.ALL" and us[0].strong
    # The reverse holds too, and synonyms named by the keywords still answer (sales are consumption).
    sales = catalog.search_catalog_scored("US electricity sales", env=ALL_KEYS, limit=20)
    assert sales[0].entry.series.startswith("usgov:eia/electricity_sales/") and sales[0].strong
    assert not any(hit.strong for hit in sales if "electricity_price" in hit.entry.series)
    consumption = catalog.search_catalog_scored("US commercial electricity consumption", env=ALL_KEYS)
    assert consumption[0].entry.series == "usgov:eia/electricity_sales/US.COM" and consumption[0].strong
    oil = catalog.search_catalog_scored("US crude oil production", env=ALL_KEYS)
    assert oil[0].entry.series == "usgov:eia/crude_production" and oil[0].strong
    assert not [hit for hit in oil if hit.entry.series == "fred:DCOILWTICO" and hit.strong]


def test_history_and_sourcing_words_are_question_framing():
    history = catalog.search_catalog_scored("fed funds rate history", env=NO_KEYS)
    assert history[0].entry.series == "fred:FEDFUNDS" and history[0].strong
    assert catalog.search_catalog_scored("historical US unemployment rate", env=NO_KEYS)[0].entry.series in (
        "fred:UNRATE", "bls:LNS14000000")
    # WDI GDP growth no longer answers "historical growth" of anything.
    semis = catalog.search_catalog_scored("historical growth rate of semiconductor sales", env=NO_KEYS, limit=50)
    wdi = "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/"
    assert not [hit for hit in semis if hit.entry.series.startswith(wdi) and hit.concept >= 4]


def test_coordinated_phrases_answer_their_clause():
    question = ("How much will US data-center electricity consumption grow by 2030, and will grid and power-price "
                "constraints slow the AI buildout?")
    keyed = catalog.search_catalog_scored(question, env=ALL_KEYS, limit=20)
    strong = [hit.entry.series for hit in keyed if hit.strong]
    assert strong[0] == "usgov:eia/electricity_sales/US.COM"
    assert {"usgov:eia/electricity_price/US.ALL", "bls:CUUR0000SEHF01"} <= set(strong[:4])
    keyless = catalog.search_catalog_scored(question, env=NO_KEYS, limit=20)
    assert "bls:CUUR0000SEHF01" in {hit.entry.series for hit in keyless if hit.strong}
    both = catalog.search_catalog_scored("US unemployment and inflation", env=NO_KEYS, limit=20)
    assert {"fred:UNRATE", "fred:CPIAUCSL"} <= {hit.entry.series for hit in both if hit.strong}
    # A coordinated phrase naming no statistic of its own adds nothing.
    core = catalog.search_catalog_scored("US CPI less food and energy", env=NO_KEYS, limit=20)
    assert {hit.entry.topics[0] for hit in core if hit.strong} == {"inflation"}


def test_a_world_aggregate_is_no_answer_where_the_country_has_the_statistic():
    china = catalog.search_catalog_scored("2027年中国实际GDP增速会低于4%吗？", env=NO_KEYS)
    world = [hit for hit in china if hit.entry.series == "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/WLD"]
    assert world and not world[0].strong
    assert catalog._WORLD_SIBLINGS["wb:WB_WDI_NY_GDP_MKTP_KD_ZG/WLD"] == {"CHN", "IND", "USA"}
    globe = catalog.search_catalog_scored("global GDP growth", env=NO_KEYS)
    assert {"wb:WB_WDI_NY_GDP_MKTP_KD_ZG/WLD", "imf:WEO/G001.NGDP_RPCH.A"} <= {hit.entry.series for hit in globe
                                                                              if hit.strong}
    # A benchmark without a national counterpart still answers a country question.
    copper = catalog.search_catalog_scored("China copper price", env=NO_KEYS)
    assert copper[0].entry.series == "fred:PCOPPUSDM" and copper[0].strong


_DISCOVERY = {  # query -> provider titles (live search 2026-10-14) and whether each shares the concept
    "global semiconductor sales": {
        "Arms exports (SIPRI trend indicator values)": False, "High-technology exports (current US$)": False,
        "Mobile cellular subscriptions": False, "Arms imports (SIPRI trend indicator values)": False,
        "Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component": True},
    "new energy vehicle sales share": {
        "Alternative and nuclear energy (% of total energy use)": False,
        "Renewable energy consumption (% of total final energy consumption)": False,
        "Share in total final energy consumption (%)": False, "Total Vehicle Sales": True},
    "US electricity retail price": {
        "Average Price: Electricity per Kilowatt-Hour in U.S. City Average": True,
        "Average Price: Ground Beef, 100% Beef (Cost per Pound/453.6 Grams) in U.S. City Average": False,
        "Fuel price levels, US$ /litre": False},
    "euro area deposit facility rate": {
        "ECB Deposit Facility Rate for Euro Area": True, "Bank liquid reserves to bank assets ratio (%)": False},
    "US data center electricity demand": {"Electric power consumption (kWh per capita)": True, "Food demand": False},
    "interest rate": {"Lending interest rate (%)": True, "Interest payments (% of revenue)": False},
    "electricity prices": {
        "Average Price: Electricity per Kilowatt-Hour in U.S. City Average": True,
        "Average Price: Ground Beef, 100% Beef (Cost per Pound/453.6 Grams) in U.S. City Average": False},
    "中国新能源汽车销量占比": {"Renewable energy consumption (% of total final energy consumption)": False,
                       "Motor vehicles (per 1,000 people)": True},
}


def test_electricity_measures_are_energy_not_consumer_spending():
    # "electricity consumption" names the energy topic only: the keyless data-center digest no longer
    # pads its related series with consumer spending and retail sales.
    assert catalog._parse_query("US electricity consumption").topics == {"energy"}
    question = _AUDIT["q2_datacenter"][0]
    related = _series_lines(catalog.catalog_digest(question, env=NO_KEYS))
    assert not {"fred:PCEC96", "fred:DPCERL1Q225SBEA", "fred:RSAFS", "fred:RRSFS"} & set(related)
    assert {"bls:CUUR0000SEHF01", "wb:WB_WDI_EG_USE_ELEC_KH_PC/USA"} <= set(related)


@pytest.mark.parametrize("query", sorted(_DISCOVERY))
def test_discovery_titles_are_judged_by_the_query_concept(query):
    terms = catalog.concept_terms(query)
    for title, expected in _DISCOVERY[query].items():
        assert catalog.shares_concept(terms, title) is expected, title
    assert catalog.shares_concept(catalog.concept_terms("China"), "Arms exports") is None  # nothing to judge


# =============================================================== digest

_QUESTIONS = {
    "china_ev": "中国新能源汽车渗透率到2030年会超过70%吗？",
    "semis": "Will global semiconductor sales exceed $1 trillion by 2030?",
    "datacenter": "How much electricity will US data centers consume in 2030?",
    "tariff": "Will US customs duties exceed $300 billion in FY2026?",
    "storage": "Will US grid battery storage capacity exceed 100 GW by 2030?",
    "election": "Will Donald Trump win the 2028 election?",
    "broad": ("Will US inflation, unemployment, GDP growth, Fed funds, 10-year yields, oil prices, the dollar, housing "
              "starts, retail sales, payrolls, wages, credit spreads, the deficit, debt, China growth and euro "
              "inflation all rise?"),
}
_HINT = "No catalog series answers this question directly"


def _series_lines(digest: str) -> list[str]:
    """Series ids listed in a digest ("- fred:UNRATE — ..."), not the provider lines ("- fred: FRED ...")."""
    return [match.group(1) for match in re.finditer(r"^- (\S+:\S+) — ", digest, re.M)]


@pytest.mark.parametrize("name", sorted(_QUESTIONS))
def test_digest_is_deterministic_bounded_and_never_pads_with_us_headlines(name):
    question = _QUESTIONS[name]
    first = catalog.catalog_digest(question, env=ALL_KEYS)
    assert first == catalog.catalog_digest(question, env=ALL_KEYS)
    assert len(first) <= 6000
    if name in ("china_ev", "semis", "election"):
        assert not {"fred:PAYEMS", "fred:UNRATE", "fred:FEDFUNDS", "fred:CPIAUCSL"} & set(_series_lines(first))


def test_weak_digests_show_related_series_and_the_search_hint():
    china = catalog.catalog_digest(_QUESTIONS["china_ev"], env=NO_KEYS)
    assert _HINT in china and "FRED search needs FRED_API_KEY" in china
    lines = _series_lines(china)
    assert "imf:PCPS/G001.PLITH.USD.M" in lines and "fred:PAYEMS" not in lines
    assert all(catalog.lookup(sid).geography in ("CHN", "WLD") for sid in lines)
    semis = catalog.catalog_digest(_QUESTIONS["semis"], env=ALL_KEYS)
    assert _HINT in semis and "FRED search covers about 800,000 series" in semis
    assert "fred:IPG3344S" in _series_lines(semis) and "fred:NASDAQSOX" in _series_lines(semis)
    election = catalog.catalog_digest(_QUESTIONS["election"], env=NO_KEYS)
    assert _series_lines(election) == [] and _HINT in election


def test_strong_digests_drop_the_hint_and_keyed_series_follow_the_environment():
    tariff = catalog.catalog_digest(_QUESTIONS["tariff"], env=NO_KEYS)
    assert _HINT not in tariff and _series_lines(tariff)[0] == "usgov:treasury/mts_customs_duties"
    keyed = catalog.catalog_digest(_QUESTIONS["datacenter"], env=ALL_KEYS)
    assert "usgov:eia/electricity_sales/US.COM" in _series_lines(keyed)
    assert "EIA electricity retail sales" in keyed and "BEA national accounts" in keyed
    keyless = catalog.catalog_digest(_QUESTIONS["datacenter"], env=NO_KEYS)
    assert "usgov:eia/" not in keyless and "usgov:bea/" not in keyless and "EIA electricity" not in keyless
    storage = catalog.catalog_digest(_QUESTIONS["storage"], env={"EIA_API_KEY": "k"})
    assert _series_lines(storage)[0] == "usgov:eia/generating_capacity/BAT"
    assert "SEC" not in tariff


_US_HEADLINES = {"fred:PAYEMS", "fred:UNRATE", "fred:FEDFUNDS", "fred:CPIAUCSL", "fred:A191RL1Q225SBEA", "fred:DGS10"}
_OIL = {"fred:DCOILBRENTEU", "fred:DCOILWTICO", "imf:PCPS/G001.POILBRE.USD.M", "imf:PCPS/G001.POILWTI.USD.M",
        "imf:WEO/G001.POILBRE.A", "imf:PCPS/G001.PNRG.INDEX.M"}
# name -> (question, env, series the digest must list first / must list, geographies allowed,
#          series it must not list, whether the "no catalog series" hint is right, strong hits required)
_FRAMING_CASES = {
    "us_inflation_and_fed": (
        _CPI_FED, NO_KEYS, ["wb:IMF_WEO_PCPIPCH/USA", "bis:WS_CBPOL/M.US", "fred:CPIAUCSL", "fred:FEDFUNDS"],
        _US_POLICY_RATE | {"bis:WS_LONG_CPI/M.US.771"}, {"USA"},
        {"bis:WS_CBPOL/M.XM", "bis:WS_CBPOL/M.CN", "wb:IMF_WEO_PCPIPCH/CHN", "fred:PAYEMS", "fred:UNRATE"}, False,
        _US_POLICY_RATE | {"fred:CPIAUCSL"}),
    "us_datacenter_power_2030": (
        "Will US data-center electricity demand exceed 500 TWh by 2030?", ALL_KEYS,
        ["usgov:eia/electricity_sales/US.COM"],
        {"usgov:eia/electricity_sales/US.ALL", "usgov:eia/net_generation/ALL"}, {"USA"},
        _US_HEADLINES | {"fred:GASREGW", "fred:DHHNGSP", "fred:IPG3344S", "usgov:eia/electricity_price/US.COM",
                         "bls:CUUR0000SEHF01"}, False,
        {"usgov:eia/electricity_sales/US.COM"}),
    "china_nev_share_2027": (
        "Will new energy vehicles exceed 60% of China's new car sales in 2027?", NO_KEYS, [],
        {"imf:PCPS/G001.PLITH.USD.M", "imf:PCPS/G001.PNICK.USD.M"}, {"CHN", "WLD"},
        _US_HEADLINES | _OIL | {"fred:TOTALSA", "bis:WS_CBPOL/M.CN", "wb:IMF_WEO_NGDP_RPCH/CHN"}, True, set()),
    "euro_policy_rate_2026": (
        "Where will the euro-area policy rate be at the end of 2026?", NO_KEYS, ["bis:WS_CBPOL/M.XM"], set(),
        {"EMU", "WLD"}, {"bis:WS_CBPOL/M.US", "fred:FEDFUNDS", "bis:WS_EER/M.R.B.XM"}, False, {"bis:WS_CBPOL/M.XM"}),
    "global_semis_2030": (
        "Will global semiconductor sales exceed $1 trillion by 2030?", ALL_KEYS, [],
        {"fred:IPG3344S", "fred:NASDAQSOX", "fred:A34SVS"}, {"USA", "WLD"},
        _US_HEADLINES | {"usgov:eia/electricity_sales/US.COM", "usgov:eia/electricity_sales/VA.COM"}, True, set()),
    "zh_china_gdp_2027": (
        "2027年中国GDP增速会低于4%吗？", NO_KEYS,
        ["wb:IMF_WEO_NGDP_RPCH/CHN", "wb:WB_GEP_NYGDPMKTPKDZ/CHN", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN"], set(),
        {"CHN", "WLD"}, _US_HEADLINES | {"wb:IMF_WEO_NGDP_RPCH/USA", "bis:WS_CBPOL/M.CN"}, False,
        {"wb:IMF_WEO_NGDP_RPCH/CHN", "wb:WB_GEP_NYGDPMKTPKDZ/CHN", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN"}),
}


@pytest.mark.parametrize("name", sorted(_FRAMING_CASES))
def test_digest_frames_diverse_forecasting_questions(name):
    question, env, first, listed, geographies, absent, hint, strong = _FRAMING_CASES[name]
    digest = catalog.catalog_digest(question, env=env)
    lines = _series_lines(digest)
    assert lines[:len(first)] == first, lines
    assert listed <= set(lines), listed - set(lines)
    assert {catalog.lookup(sid).geography for sid in lines} <= geographies, lines
    assert not absent & set(lines), absent & set(lines)
    assert (_HINT in digest) is hint and "part of this question" not in digest
    assert len(digest) <= 6000
    hits = catalog.search_catalog_scored(question, env=env, limit=50)
    assert strong <= {hit.entry.series for hit in hits if hit.strong}
    assert bool(strong) is any(hit.strong for hit in hits)


# The six agent-usage audit questions (2026-10-13): name -> (question, env, digest's first direct series,
# strong hits required, strong hits forbidden, geographies the digest may list, whether the "no
# catalog series" hint is right).
_AUDIT = {
    "q1_cpi_fed": (
        _CPI_FED, NO_KEYS, ["wb:IMF_WEO_PCPIPCH/USA", "bis:WS_CBPOL/M.US", "fred:CPIAUCSL", "fred:FEDFUNDS"],
        _US_POLICY_RATE | {"fred:CPIAUCSL", "wb:IMF_WEO_PCPIPCH/USA"}, {"fred:ECBDFR", "bis:WS_CBPOL/M.XM"},
        {"USA"}, False),
    "q2_datacenter": (
        "How much will US data-center electricity consumption grow by 2030, and will grid and power-price "
        "constraints slow the AI buildout?", ALL_KEYS,
        ["usgov:eia/electricity_sales/US.COM", "bls:CUUR0000SEHF01"],
        {"usgov:eia/electricity_sales/US.COM", "usgov:eia/electricity_price/US.ALL", "bls:CUUR0000SEHF01"},
        {"usgov:eia/electricity_sales/US.ALL", "fred:PCEC96"}, {"USA"}, False),
    "q3_china_nev": (
        "Will China's new-energy-vehicle share of car sales exceed 60% in 2027?", NO_KEYS, [], set(),
        {"fred:TOTALSA"}, {"CHN", "WLD"}, True),
    "q4_ecb_dfr": (
        "What will the euro-area deposit facility rate be at the end of 2026?", NO_KEYS,
        ["fred:ECBDFR", "bis:WS_CBPOL/M.XM"], {"fred:ECBDFR", "bis:WS_CBPOL/M.XM"},
        {"bis:WS_EER/M.R.B.XM", "usgov:treasury/fx/Euro Zone-Euro"}, {"EMU"}, False),
    "q5_semis": (
        "Will global semiconductor sales exceed $1 trillion by 2030?", ALL_KEYS, [], set(),
        {"fred:IPG3344S", "usgov:eia/electricity_sales/US.COM"}, {"USA", "WLD"}, True),
    "q6_china_gdp_zh": (
        "2027年中国实际GDP增速会低于4%吗？", NO_KEYS,
        ["wb:IMF_WEO_NGDP_RPCH/CHN", "wb:WB_GEP_NYGDPMKTPKDZ/CHN", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN"],
        {"wb:IMF_WEO_NGDP_RPCH/CHN", "wb:WB_GEP_NYGDPMKTPKDZ/CHN", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN"},
        {"wb:WB_WDI_NY_GDP_MKTP_KD_ZG/WLD", "imf:WEO/G001.NGDP_RPCH.A"}, {"CHN", "WLD"}, False),
}


@pytest.mark.parametrize("name", sorted(_AUDIT))
def test_audit_questions_search_and_digest(name):
    question, env, first, strong, weak, geographies, hint = _AUDIT[name]
    hits = catalog.search_catalog_scored(question, env=env, limit=50)
    found = [hit.entry.series for hit in hits if hit.strong]
    assert strong <= set(found) and not weak & set(found), found
    assert _ids(hits)[:len(found)] == found  # strong matches lead
    digest = catalog.catalog_digest(question, env=env)
    lines = _series_lines(digest)
    assert lines[:len(first)] == first, lines
    assert {catalog.lookup(sid).geography for sid in lines} <= geographies, lines
    assert (_HINT in digest) is hint and "part of this question" not in digest
    assert not {"fred:PAYEMS", "fred:UNRATE"} & set(lines) and len(digest) <= 6000
    if not strong:
        assert not found


def test_audit_questions_name_their_economy():
    expected = {"q1_cpi_fed": {"USA"}, "q2_datacenter": {"USA"}, "q3_china_nev": {"CHN"}, "q4_ecb_dfr": {"EMU"},
                "q5_semis": {"WLD"}, "q6_china_gdp_zh": {"CHN"}}
    for name, (question, *_rest) in _AUDIT.items():
        assert catalog.query_geographies(question) == expected[name], name
        assert catalog.query_geographies(AGENT_USAGE["questions"][name]["question"]) == expected[name], name


def test_digest_names_the_clauses_no_catalog_series_answers():
    question = "Will US CPI inflation exceed 3% in 2027, and how will the Atlanta Fed wage tracker evolve?"
    digest = catalog.catalog_digest(question, env=NO_KEYS)
    assert _HINT not in digest and _series_lines(digest)[:2] == ["wb:IMF_WEO_PCPIPCH/USA", "fred:CPIAUCSL"]
    assert ('No catalog series answers part of this question directly ("how will the Atlanta Fed wage tracker '
            'evolve"): search that part with short English concept terms; FRED search needs FRED_API_KEY') in digest
    # A question naming an economy but no theme still gets that economy's headline series.
    china = _series_lines(catalog.catalog_digest("What will happen to China in 2027?", env=NO_KEYS))
    assert "wb:IMF_WEO_NGDP_RPCH/CHN" in china and {catalog.lookup(sid).geography for sid in china} == {"CHN"}


# =============================================================== skill reference files

def test_reference_files_match_the_generator_and_stay_readable():
    rendered = catalog.render_catalog_files()
    refs = SKILL_DIR / "references"
    on_disk = {path.name: path.read_text(encoding="utf-8") for path in refs.glob("*.md")}
    assert set(on_disk) == set(rendered), "regenerate: python deerflow_bridge/data_catalog.py --write-markdown"
    for name, text in rendered.items():
        assert on_disk[name] == text, f"{name} is stale; regenerate with --write-markdown"
        assert len(text) < 40_000, name  # deer-flow read_file truncates at 50,000 chars
    index = rendered[catalog.REFERENCE_INDEX]
    for heading in ("## Id grammar", "### BIS dataflows", "### IMF dataflows", "### usgov recipes"):
        assert heading in index
    for entry in catalog.CATALOG:
        assert f"`{entry.series}`" in rendered[f"catalog-{entry.provider}.md"]


def test_skill_points_at_every_reference_and_keeps_a_compact_body():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) < 8_000
    front = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert front and [line.split(":", 1)[0] for line in front.group(1).splitlines()] == ["name", "description"]
    for name in catalog.render_catalog_files():
        assert f"references/{name}" in text, name
    for code in ("invalid_window", "rate_limited", "quota_exhausted", "key_invalid", "provider_unavailable"):
        assert code in text
    for phrase in ("EIA_API_KEY", "BEA_API_KEY", "FRED_API_KEY", "`projection`", "`partial`", "SEC company facts",
                   "Search each measurable part of a compound question on its own"):
        assert phrase in text


def test_main_writes_every_reference_file(tmp_path, capsys):
    assert catalog.main(["--write-markdown", str(tmp_path)]) == 0
    assert {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()} == catalog.render_catalog_files()
    assert catalog.main(["--write-markdown", str(tmp_path / "missing")]) == 1
    assert catalog.main(["--bogus"]) == 2
    capsys.readouterr()


@pytest.mark.parametrize("query, rate_series, balance_sheet", [
    ("Will China's central bank cut its policy rate in 2027?", "bis:WS_CBPOL/M.CN", "bis:WS_CBTA/M.CN.B.XDC.CNY.N"),
    ("US central bank interest rate", "bis:WS_CBPOL/M.US", "bis:WS_CBTA/M.US.B.XDC.USD.N"),
    ("Will the European Central Bank cut rates in 2027?", "bis:WS_CBPOL/M.XM", "bis:WS_CBTA/M.XM.B.XDC.EUR.N"),
])
def test_a_rate_question_never_takes_a_central_bank_balance_sheet_as_strong(query, rate_series, balance_sheet):
    """'Central bank' in the title plus the policy topic made total assets a strong match for a rate
    question, so the legacy pre-pass fetched the balance sheet (DATA-R7-2)."""
    strong = {hit.entry.series for hit in catalog.search_catalog_scored(query, limit=8) if hit.strong}
    assert rate_series in strong and balance_sheet not in strong


@pytest.mark.parametrize("query, balance_sheet", [
    ("US central bank balance sheet", "bis:WS_CBTA/M.US.B.XDC.USD.N"),
    ("中国央行资产负债表规模", "bis:WS_CBTA/M.CN.B.XDC.CNY.N"),
    ("Will the Fed end quantitative tightening in 2026?", "fred:WALCL"),
])
def test_balance_sheet_questions_keep_their_balance_sheet_series(query, balance_sheet):
    assert balance_sheet in {hit.entry.series for hit in catalog.search_catalog_scored(query, limit=8) if hit.strong}
