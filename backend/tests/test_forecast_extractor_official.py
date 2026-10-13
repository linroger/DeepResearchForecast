"""Official-data forecast math on REAL stored carriers (fix contract §1.8).

Covers RPT-3 (data anchors reachable from natural EN/ZH prose — series aliases, Chinese
dates, comparator words — canonical settlement sentence, and the ``auto_resolvable`` flag
the resolution monitor reads), RPT-4/I1 (empirical h-step base rate, fan and outside view
from complete history only; the seasonal basis of monthly series without seasonal adjustment), RPT-6 (partial periods are never history), RPT-9 (structured scenario
``metric_range``), RPT-15 (one value format in tables), MISSED-2 (World Bank WDI
history under the current status policy) and downstream M1 (exact WEO/GEP prefixes).

Carriers are live captures (backend/tests/fixtures/data_sources/real/): the
2026-10-11 report carrier (12 rows, normalization policy 2) and the policy-3 history
rows; provider captures are replayed through the current data layer.
"""
from __future__ import annotations

import json
import math
import operator
from copy import deepcopy
from pathlib import Path

import pytest

from app.services import forecast_extractor as fe
from app.services.official_data import validate_data_anchor
from tests.conftest import FakeLLMClient

REAL = Path(__file__).parent / "fixtures" / "data_sources" / "real"
_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


@pytest.fixture(autouse=True)
def forbid_fetch(monkeypatch):
    from app.services import official_data as adapter

    def forbidden(*args, **kwargs):
        pytest.fail("Forecast math attempted to acquire an upstream data client")
    monkeypatch.setattr(adapter, "get_data_sources", forbidden)
    api = adapter.data_api()
    if api is not None and hasattr(api, "get_data_sources"):
        monkeypatch.setattr(api, "get_data_sources", forbidden)


def _load(name: str) -> dict:
    return json.loads((REAL / name).read_text())


@pytest.fixture
def carrier() -> dict:
    return _load("forecast_carrier-2026-10-11.json")


@pytest.fixture
def history() -> dict:
    return _load("forecast_history_v3-2026-10-11.json")


def _row(official_data: dict, series: str) -> dict:
    return next(r for r in fe.official_series_rows(official_data) if r["series"] == series)


def _replayed(name: str, tmp_path: Path) -> dict:
    from official_data_replay import replay
    return replay(name, tmp_path).to_dict()


UNRATE_GE5 = {"series": "fred:UNRATE", "comparator": ">=", "threshold": 5, "observation": "2027-06",
              "units": "Percent", "transform": ""}
STATEMENT = "The US unemployment rate is at least 5% in June 2027"
CRITERIA = "fred:UNRATE >= 5% in 2027-06"
EN_SETTLEMENT = "Official resolution: fred:UNRATE >= 5% for 2027-06."
ZH_SETTLEMENT = "官方判定：fred:UNRATE >= 5%，观察期 2027-06。"


def _binary(official_data, statement=STATEMENT, criteria=CRITERIA, anchor=UNRATE_GE5, language="English",
            probability=0.3):
    options = {} if language == "English" else {"language": language}  # English is the default
    return fe._normalize_binaries([{"statement": statement, "probability": probability,
                                    "resolution_criteria": criteria, "data_anchor": dict(anchor)}],
                                  official_data=official_data, **options)[0]


# --------------------------------------------------------------------------- RPT-3


@pytest.mark.parametrize("criteria", [
    "fred:UNRATE >= 5% in 2027-06 (source: FRED).",
    "fred:UNRATE >= 5% in 2027-06, per the BLS release on FRED.",
    "Resolves YES if fred:UNRATE >= 5% in 2027-06.",
    "YES if fred:UNRATE >= 5% for June 2027, as published by FRED.",
    "若 fred:UNRATE >= 5%（2027-06），判定为是（数据来源：FRED）。",
    "fred:UNRATE >= 5% 于 2027-06，以FRED发布值为准。",
])
def test_realistic_criteria_admit_the_anchor_with_one_settlement_sentence(carrier, criteria):
    binary = _binary(carrier, criteria=criteria)
    assert binary["data_anchor"]["series"] == "fred:UNRATE"
    assert binary["data_anchor"]["period"] == "2027-06-01"
    assert binary["resolution_criteria"].startswith(criteria)
    assert binary["resolution_criteria"].count(EN_SETTLEMENT) == 1
    assert binary["probability"] == 0.3


@pytest.mark.parametrize("statement", [
    "The US unemployment rate >= 5% in June 2027",
    "US unemployment rate reaches at least 5% in June 2027",
    "The U.S. jobless rate is 5% or higher in June 2027",
    "失业率 >= 5% 2027年6月",
    "美国失业率在2027年6月 >= 5%",
    "美国失业率在2027年6月不低于5%",
])
def test_natural_english_and_chinese_statements_admit_the_anchor(carrier, statement):
    binary = _binary(carrier, statement=statement)
    assert binary["data_anchor"]["series"] == "fred:UNRATE"


@pytest.mark.parametrize("statement", [
    "The US unemployment rate is not at least 5% in June 2027",
    "The US unemployment rate is at least 5% in July 2027",
    "The US unemployment rate is at least 5% by June 2027",
    "The US unemployment rate is at least 5% and payrolls fall in June 2027",
    "If the Fed cuts, the US unemployment rate is at least 5% in June 2027",
    "The US unemployment rate is at most 5% in June 2027",
    "The US unemployment rate is at least 6% in June 2027",
    "The UK unemployment rate is at least 5% in June 2027",
    "The US unemployment rate is at least 5 percentage points in June 2027",
    "The US unemployment rate is at least 5% in June 2027 or 4.5% in May 2027",
    "Payrolls grow at least 5% in June 2027",
])
def test_statements_with_another_proposition_stay_unanchored(carrier, statement):
    binary = _binary(carrier, statement=statement)
    assert "data_anchor" not in binary
    assert binary["resolution_criteria"] == CRITERIA


@pytest.mark.parametrize("criteria", [
    "fred:UNRATE >= 5% in 2027-06 or fred:UNRATE >= 4.5% in 2027-05",
    "fred:UNRATE >= 5% in 2027-07",
    "fred:UNRATE >= 5% by 2027-06",
    "fred:UNRATE >= 5% in 2027-06 unless revised",
    "If the Fed cuts, fred:UNRATE >= 5% in 2027-06",
    "fred:UNRATE >= 5.5% in 2027-06",
    "fred:UNRATE > 5% in 2027-06",
    "fred:UNRATE >= 5% in 2027-06 (source: FRED), then 4% in 2027-12",
    "Unemployment >= 5% in 2027-06 (source: FRED)",
])
def test_criteria_without_exactly_one_canonical_clause_stay_unanchored(carrier, criteria):
    binary = _binary(carrier, criteria=criteria)
    assert "data_anchor" not in binary
    assert binary["resolution_criteria"] == criteria


def test_settlement_sentence_is_idempotent_and_follows_the_report_language(carrier):
    english = _binary(carrier)
    again = _binary(carrier, criteria=english["resolution_criteria"])
    assert again["resolution_criteria"] == english["resolution_criteria"]
    assert again["data_anchor"]["series"] == "fred:UNRATE"
    chinese = _binary(carrier, statement="美国失业率在2027年6月不低于5%", language="Chinese")
    assert chinese["resolution_criteria"] == f"{CRITERIA} {ZH_SETTLEMENT}"
    assert chinese["criteria_sharp"] is True


def test_large_level_settlement_uses_one_value_format(carrier):
    anchor = {"series": "usgov:treasury/debt_to_penny", "comparator": ">", "threshold": 45e12,
              "observation": "2027-12", "units": "U.S. dollars"}
    binary = _binary(carrier, statement="US public debt exceeds $45 trillion in December 2027",
                     criteria="usgov:treasury/debt_to_penny > 45000000000000 U.S. dollars in 2027-12",
                     anchor=anchor)
    assert binary["resolution_criteria"].endswith(
        "Official resolution: usgov:treasury/debt_to_penny > 45000000000000 U.S. dollars "
        "(≈ 45 trillion U.S. dollars) for 2027-12.")
    assert "4.5e+13" not in binary["resolution_criteria"]
    zh = _binary(carrier, statement="美国联邦公共债务总额在2027年12月超过45万亿美元",
                 criteria="usgov:treasury/debt_to_penny > 45000000000000 U.S. dollars（2027-12），数据来源：美国财政部。",
                 anchor=anchor, language="Chinese")
    assert zh["resolution_criteria"].endswith(
        "官方判定：usgov:treasury/debt_to_penny > 45000000000000（≈45万亿美元）（单位 `U.S. dollars`），观察期 2027-12。")


GDPC1 = {"series": "fred:GDPC1", "comparator": ">", "threshold": 24500, "observation": "2027-Q2",
         "units": "Billions of Chained 2017 Dollars"}


@pytest.mark.parametrize("statement, criteria, admitted", [
    ("US real GDP exceeds $24.5 trillion (chained 2017 dollars) in 2027-Q2",
     "Resolves YES if fred:GDPC1 > 24500 Billions of Chained 2017 Dollars in 2027-Q2 (source: BEA via FRED).", True),
    ("US real GDP exceeds 24,500 billion chained 2017 dollars in Q2 2027", "fred:GDPC1 > 24500 in 2027-Q2", True),
    ("美国实际国内生产总值在2027年第二季度超过24.5万亿美元", "fred:GDPC1 > 24.5 trillion in 2027-Q2", True),
    ("US real GDP exceeds $24.5 billion in 2027-Q2", "fred:GDPC1 > 24500 in 2027-Q2", False),
    ("US real GDP exceeds $24.5 trillion in 2027-Q2", "fred:GDPC1 > 24500 billion billion in 2027-Q2", False),
])
def test_scaled_units_compare_in_the_series_units(carrier, statement, criteria, admitted):
    binary = _binary(carrier, statement=statement, criteria=criteria, anchor=GDPC1, probability=0.6)
    assert ("data_anchor" in binary) is admitted
    if admitted:
        assert binary["resolution_criteria"].endswith(
            "Official resolution: fred:GDPC1 > 24500 Billions of Chained 2017 Dollars for 2027-Q2.")


def test_zh_statement_matches_title_without_its_trailing_qualifier(carrier):
    anchor = {"series": "fred:FEDFUNDS", "comparator": "<", "threshold": 3.5, "observation": "2027-03",
              "units": "Percent"}
    binary = _binary(carrier, statement="联邦基金有效利率在2027年3月低于3.5%",
                     criteria="fred:FEDFUNDS < 3.5% 于 2027-03（来源：FRED）。", anchor=anchor, language="Chinese")
    assert _row(carrier, "fred:FEDFUNDS")["title_zh"] == "联邦基金有效利率（月均）"
    assert binary["data_anchor"]["series"] == "fred:FEDFUNDS"


SPREAD_LT0 = {"series": "fred:T10Y3M", "comparator": "<", "threshold": 0, "observation": "2027-06",
              "units": "Percent", "transform": ""}
SPREAD_CRITERIA = "Resolves YES if fred:T10Y3M < 0% in 2027-06 (source: FRED)."
FUNDS_LT3 = {"series": "fred:FEDFUNDS", "comparator": "<", "threshold": 3, "observation": "2027-12",
             "units": "Percent", "transform": ""}
FUNDS_STATEMENT_ZH = "联邦基金有效利率在2027年12月 < 3%"
FUNDS_CRITERIA_ZH = "若fred:FEDFUNDS于2027年12月低于3%，判定为是（数据来源：FRED）。"
FUNDS_SETTLEMENT_ZH = "官方判定：fred:FEDFUNDS < 3%，观察期 2027-12。"
DGS10_GE5 = {"series": "fred:DGS10", "comparator": ">=", "threshold": 5, "observation": "2027-06",
             "units": "Percent", "transform": ""}


def test_reported_spread_and_fed_funds_phrasings_anchor(carrier):
    """The two binaries the G1 live publication run left without an anchor."""
    spread = _binary(carrier, statement="The 10-year minus 3-month Treasury spread < 0% in June 2027",
                     criteria=SPREAD_CRITERIA, anchor=SPREAD_LT0, probability=0.25)
    assert spread["data_anchor"]["series"] == "fred:T10Y3M" and spread["probability"] == 0.25
    assert spread["resolution_criteria"] == f"{SPREAD_CRITERIA} Official resolution: fred:T10Y3M < 0% for 2027-06."
    funds = _binary(carrier, statement=FUNDS_STATEMENT_ZH, criteria=FUNDS_CRITERIA_ZH, anchor=FUNDS_LT3,
                    language="Chinese", probability=0.45)
    assert funds["data_anchor"]["series"] == "fred:FEDFUNDS"
    assert funds["resolution_criteria"] == f"{FUNDS_CRITERIA_ZH} {FUNDS_SETTLEMENT_ZH}"


@pytest.mark.parametrize("statement, anchor, criteria", [
    ("The 10-year minus 3-month Treasury spread is below 0% in June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("The 10-year/3-month Treasury spread is below 0% in June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("The spread between the 10-year and 3-month Treasury yields is below 0% in June 2027", SPREAD_LT0,
     SPREAD_CRITERIA),
    ("The 10Y-3M Treasury spread is below zero in June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("The T10Y3M spread turns negative in June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("联邦基金有效利率在 2027 年 12 月 < 3%", FUNDS_LT3, "fred:FEDFUNDS < 3% 于 2027-12"),
    ("联邦基金有效利率2027年12月＜3％", FUNDS_LT3, "fred:FEDFUNDS < 3% 于 2027-12"),
    ("联邦基金有效利率在2027年12月份不到3%", FUNDS_LT3, "fred:FEDFUNDS < 3% 于 2027-12"),
    ("The US unemployment rate is at or above 5% in June 2027", UNRATE_GE5, CRITERIA),
    ("US unemployment rises to 5% or higher in June 2027", UNRATE_GE5, CRITERIA),
    ("美国失业率在2027年6月份达到5%及以上", UNRATE_GE5, CRITERIA),
    ("美国失业率在 2027 年 6 月为5%或以上", UNRATE_GE5, CRITERIA),
])
def test_series_aliases_period_and_comparator_forms_admit_the_anchor(carrier, statement, anchor, criteria):
    binary = _binary(carrier, statement=statement, criteria=criteria, anchor=anchor)
    assert binary["data_anchor"]["series"] == anchor["series"]


@pytest.mark.parametrize("criteria", [
    FUNDS_CRITERIA_ZH,
    "若 fred:FEDFUNDS 在 2027 年 12 月 < 3%，则判定为“是”（数据来源：FRED）。",
    "当 fred:FEDFUNDS 2027-12 < 3% 时判定为是",
    "fred:FEDFUNDS < 3%，观察期 2027-12。",
    "以 FRED 公布的 fred:FEDFUNDS 2027-12 月度值 < 3% 判定为是",
    "Resolves YES if fred:FEDFUNDS is below 3% in 2027-12 (source: FRED).",
])
def test_criteria_with_word_comparators_and_chinese_framing_admit_the_anchor(carrier, criteria):
    binary = _binary(carrier, statement=FUNDS_STATEMENT_ZH, criteria=criteria, anchor=FUNDS_LT3, language="Chinese")
    assert binary["data_anchor"]["series"] == "fred:FEDFUNDS"
    assert binary["resolution_criteria"] == f"{criteria} {FUNDS_SETTLEMENT_ZH}"


@pytest.mark.parametrize("statement, anchor, criteria", [
    ("The 10-year minus 3-month Treasury spread is not below 0% in June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("The 10-year minus 3-month Treasury spread is below 0% in July 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("The 10-year minus 3-month Treasury spread is below 0% by June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("The 10-year minus 2-year Treasury spread is below 0% in June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("The 10-year minus 3-month Treasury spread is non-negative in June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("The 10-year minus 3-month Treasury spread is negative and the Fed cuts in June 2027", SPREAD_LT0,
     SPREAD_CRITERIA),
    ("The German 10-year minus 3-month spread is below 0% in June 2027", SPREAD_LT0, SPREAD_CRITERIA),
    ("联邦基金有效利率在 2027 年 11 月 < 3%", FUNDS_LT3, "fred:FEDFUNDS < 3% 于 2027-12"),
    ("到2027年12月联邦基金有效利率 < 3%", FUNDS_LT3, "fred:FEDFUNDS < 3% 于 2027-12"),
    ("联邦基金有效利率在2027年12月 < 3% 且失业率上升", FUNDS_LT3, "fred:FEDFUNDS < 3% 于 2027-12"),
    ("联邦基金期货隐含利率在2027年12月 < 3%", FUNDS_LT3, "fred:FEDFUNDS < 3% 于 2027-12"),
    ("实际联邦基金利率在2027年12月 < 3%", FUNDS_LT3, "fred:FEDFUNDS < 3% 于 2027-12"),
    ("The market-implied federal funds rate is below 3% in December 2027", FUNDS_LT3,
     "fred:FEDFUNDS < 3% in 2027-12"),
    ("The effective federal funds rate is at or below 3% in December 2027", FUNDS_LT3,
     "fred:FEDFUNDS < 3% in 2027-12"),
    ("The youth unemployment rate is at least 5% in June 2027", UNRATE_GE5, CRITERIA),
    ("美国青年失业率在2027年6月不低于5%", UNRATE_GE5, CRITERIA),
    ("The US unemployment rate is not at or above 5% in June 2027", UNRATE_GE5, CRITERIA),
    ("美国失业率在2027年6月未达到5%及以上", UNRATE_GE5, CRITERIA),
    ("The real 10-year Treasury yield is at least 5% in June 2027", DGS10_GE5, "fred:DGS10 >= 5% in 2027-06"),
    ("The 10-year TIPS yield is at least 5% in June 2027", DGS10_GE5, "fred:DGS10 >= 5% in 2027-06"),
    ("The 2-year Treasury yield is at least 5% in June 2027", DGS10_GE5, "fred:DGS10 >= 5% in 2027-06"),
])
def test_broadened_forms_keep_other_propositions_unanchored(carrier, statement, anchor, criteria):
    binary = _binary(carrier, statement=statement, criteria=criteria, anchor=anchor)
    assert "data_anchor" not in binary
    assert binary["resolution_criteria"] == criteria


@pytest.mark.parametrize("criteria", [
    "若fred:FEDFUNDS于2027年12月不低于3%，判定为是",
    "若fred:FEDFUNDS于2027年11月低于3%，判定为是",
    "fred:FEDFUNDS does not exceed 3% in 2027-12",
    "当 fred:FEDFUNDS 2027-12 < 3% 时判定为否",
    "fred:FEDFUNDS < 3%，观察期 2027-11",
    "fred:FEDFUNDSX < 3% in 2027-12",
])
def test_word_comparator_criteria_still_need_the_exact_clause(carrier, criteria):
    binary = _binary(carrier, statement=FUNDS_STATEMENT_ZH, criteria=criteria, anchor=FUNDS_LT3, language="Chinese")
    assert "data_anchor" not in binary


def test_target_range_limits_name_their_own_series(tmp_path):
    official_data = {"schema_version": 1, "series": [_replayed("fred_dfedtaru_daily_step", tmp_path)]}
    anchor = {"series": "fred:DFEDTARU", "comparator": ">=", "threshold": 4.5, "observation": "2026-12",
              "units": "Percent"}
    criteria = "Resolves YES if fred:DFEDTARU >= 4.5% in 2026-12 (source: FRED)."
    for statement, admitted in [
            ("The upper bound of the federal funds target range is at least 4.5% in December 2026", True),
            ("联邦基金目标利率区间上限在2026年12月不低于4.5%", True),
            ("The lower bound of the federal funds target range is at least 4.5% in December 2026", False),
            ("联邦基金目标利率区间下限在2026年12月不低于4.5%", False)]:
        binary = _binary(official_data, statement=statement, criteria=criteria, anchor=anchor)
        assert ("data_anchor" in binary) is admitted, statement


def test_acronym_and_bare_native_id_name_the_series():
    """Real-run shape: 'The US CPI index level (CPIAUCSL, SA) is at least …' lost its anchor."""
    row = _load("visuals/current/fred_cpiaucsl_yoy.json")
    official_data = {"schema_version": 1, "series": [row]}
    anchor = {"series": "fred:CPIAUCSL#yoy", "comparator": ">=", "threshold": 3, "observation": "2027-06",
              "units": row["units"], "transform": "yoy"}
    criteria = "Resolves YES if fred:CPIAUCSL#yoy >= 3% in 2027-06 (source: FRED)."
    for statement, admitted in [("US CPI inflation (CPIAUCSL, SA) is at least 3% in June 2027", True),
                                ("美国CPI同比在2027年6月不低于3%", True),
                                ("US core CPI inflation is at least 3% in June 2027", False),
                                ("US PCE inflation is at least 3% in June 2027", False)]:
        binary = _binary(official_data, statement=statement, criteria=criteria, anchor=anchor)
        assert ("data_anchor" in binary) is admitted, statement


def test_extraction_prompt_carries_worked_example_and_outside_view_only_with_data(carrier):
    calls = []

    class LLM:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096):
            calls.append(messages[0]["content"])
            return {"binary_forecasts": [{"statement": STATEMENT, "probability": 0.3,
                                          "resolution_criteria": CRITERIA, "data_anchor": dict(UNRATE_GE5)}]}

    out = fe.extract_binary_forecasts("report", LLM(), min_count=1, horizon_date="2027-12-31",
                                      data_pack="[Official data snapshot]\nfred:UNRATE 4.2%", official_data=carrier)
    assert out["binary_forecasts"][0]["data_anchor"]["empirical_base_rate"]["n"] == 108
    assert '"resolution_criteria": "Resolves YES if fred:UNRATE >= 5% in 2027-06 (source: FRED)."' in calls[0]
    assert "[Official history — outside view" in calls[0]
    calls.clear()
    fe.extract_binary_forecasts("report", LLM(), min_count=1, horizon_date="2027-12-31")
    assert "[Official history" not in calls[0] and "data_anchor" not in calls[0]
    assert "Format illustration only" not in calls[0]


# ------------------------------------------------------------- RPT-4 / I1 (§1.8)


def _brute_force_base_rate(row: dict, comparator: str, threshold: float, target: str):
    """Independent re-derivation: monthly ordinal -> value, all h-step changes."""
    def ordinal(day: str) -> int:
        return int(day[:4]) * 12 + int(day[5:7]) - 1
    values = {ordinal(p["date"]): p["value"] for p in row["observations"] if p["value"] is not None}
    latest = max(values)
    steps = ordinal(target) - latest
    changes = [values[i + steps] - values[i] for i in values if i + steps in values]
    hits = sum(_OPS[comparator](round(values[latest] + c, 9), threshold) for c in changes)
    mean = sum(changes) / len(changes)
    sd = math.sqrt(sum((c - mean) ** 2 for c in changes) / (len(changes) - 1))
    return round(hits / len(changes), 4), len(changes), steps, round((threshold - values[latest]) / sd, 2)


@pytest.mark.parametrize("fixture, comparator, threshold, expected_n", [
    ("forecast_carrier-2026-10-11.json", ">=", 5, 108),
    ("forecast_carrier-2026-10-11.json", "<=", 4, 108),
    ("forecast_history_v3-2026-10-11.json", ">=", 5, 229),
    ("forecast_history_v3-2026-10-11.json", "<", 4, 229),
])
def test_empirical_base_rate_is_the_deterministic_h_step_share(fixture, comparator, threshold, expected_n):
    official_data = _load(fixture)
    row = _row(official_data, "fred:UNRATE")
    anchor = validate_data_anchor({**UNRATE_GE5, "comparator": comparator, "threshold": threshold}, official_data)
    base = fe.official_empirical_base_rate(row, anchor)
    p, n, h, sigma = _brute_force_base_rate(row, comparator, threshold, "2027-06-01")
    assert (base["p"], base["n"], base["h"], base["sigma_distance"]) == (p, n, h, sigma)
    assert (n, h) == (expected_n, 9)
    assert base["method"] == "empirical_h_step"
    assert base["latest"] == {"date": "2026-09-01", "value": 4.2}
    assert base["window"]["end"] == "2026-09-01"
    q = base["quantiles"]
    assert q["p10"] <= q["p25"] <= q["p50"] <= q["p75"] <= q["p90"]


def test_admitted_anchor_carries_display_latest_and_base_rate_without_changing_probability(carrier):
    binary = _binary(carrier, probability=0.3)
    anchor = binary["data_anchor"]
    assert (anchor["latest_value"], anchor["latest_date"]) == (4.2, "2026-09-01")
    assert anchor["empirical_base_rate"]["p"] == 0.0926
    assert binary["probability"] == 0.3


def test_short_history_has_no_base_rate_or_fan(carrier):
    row = _row(carrier, "usgov:treasury/debt_to_penny")
    anchor = validate_data_anchor({"series": row["series"], "comparator": ">", "threshold": 45e12,
                                   "observation": "2027-12", "units": "U.S. dollars"}, carrier)
    assert fe.official_empirical_base_rate(row, anchor) is None
    assert fe.official_empirical_fan(row, "2027-12-01") == []


def test_projections_estimates_and_partial_periods_never_enter_the_outside_view(tmp_path, history):
    weo = _replayed("imf_weo_usa_ngdp_rpch_default_window", tmp_path)
    kinds = fe.official_observation_kinds(weo)
    assert kinds.count("publisher projection") == 6 and kinds.count("publisher estimate") == 1
    observed = fe._official_history(weo)
    assert [d for _i, d, _v in observed][-1] == "2024-01-01" and len(observed) == 23
    assert fe.official_latest_observed(weo) == {"date": "2024-01-01", "value": 2.793116}
    anchor = validate_data_anchor({"series": weo["series"], "comparator": ">=", "threshold": 2,
                                   "observation": "2027", "units": weo["units"]}, {"schema_version": 1,
                                                                                    "series": [weo]})
    assert fe.official_empirical_base_rate(weo, anchor) is None  # 20 samples < 30
    dgs10 = _row(history, "fred:DGS10")
    assert fe.official_observation_kinds(dgs10)[-1] == "partial-period value"
    assert [d for _i, d, _v in fe._official_history(dgs10)][-1] == "2026-09-01"
    unrate = _row(history, "fred:UNRATE")
    fan = fe.official_empirical_fan(unrate, "2027-06-01")
    assert [p["date"] for p in fan] == [f"2026-{m:02d}-01" for m in (10, 11, 12)] + [
        f"2027-{m:02d}-01" for m in range(1, 7)]
    assert all(p["n"] >= fe.EMPIRICAL_MIN_SAMPLES for p in fan)
    assert all(p["p10"] <= p["p50"] <= p["p90"] for p in fan)


def test_outside_view_block_is_deterministic_bounded_and_bilingual(carrier):
    block = fe.official_outside_view_block(carrier, "2027-12-31", "English")
    assert block.startswith("[Official history — outside view")
    line = next(l for l in block.splitlines() if "(fred:UNRATE)" in l)
    # 119 stored months, one of them the missing October 2025 release (value null).
    assert "latest 4.2% (2026-09)" in line and "118 historical months 2016-11 to 2026-09" in line
    assert "; 15-month change to the horizon 2027-12 (n=103): p10 " in line and " pp" in line
    dgs10 = next(l for l in block.splitlines() if "(fred:DGS10)" in l)
    assert "(2026-09)" in dgs10  # the partial October mean is not the latest value
    assert "(imf:WEO/G001.NGDP_RPCH.A)" not in block  # no complete history under policy 2
    assert block == fe.official_outside_view_block(deepcopy(carrier), "2027-12-31", "English")
    zh = fe.official_outside_view_block(carrier, "2027-12-31", "Chinese")
    assert zh.startswith("【官方历史·外部视角") and "美国失业率（fred:UNRATE）：最新 4.2%（2026-09）" in zh
    short = fe.official_outside_view_block(carrier, "2027-12-31", "English", max_chars=900)
    assert len(short) <= 900 and short.splitlines()[-2].endswith("further series omitted for length)")
    assert fe.official_outside_view_block(None) == "" and fe.official_outside_view_block({}) == ""


def test_base_rate_divergence_is_flagged_never_applied(carrier):
    binaries = [_binary(carrier, probability=0.3),
                _binary(carrier, statement="US unemployment rate is at most 4% in June 2027",
                        criteria="fred:UNRATE <= 4% in 2027-06",
                        anchor={**UNRATE_GE5, "comparator": "<=", "threshold": 4}, probability=0.2)]
    binaries[1]["id"] = "F2"
    quality = fe._binary_quality(binaries, min_count=1)
    assert quality["base_rate_divergence"] == [{"id": "F2", "probability": 0.2, "empirical_p": 0.4722,
                                                "divergence": -0.2722}]
    assert any("empirical base rate by more than 25 pp: F2" in issue for issue in quality["issues"])
    assert [b["probability"] for b in binaries] == [0.3, 0.2]
    plain = fe._binary_quality([{**b, "data_anchor": None} for b in binaries], min_count=1)
    assert "base_rate_divergence" not in plain


# ------------------------------- seasons of monthly series without seasonal adjustment

EIA_COM = "usgov:eia/electricity_sales/US.COM"
EIA_COM_STATEMENT = ("US commercial-sector retail electricity sales are at least 140,000 million kilowatt-hours "
                     "in December 2026.")
EIA_COM_CRITERIA = (f"Resolves YES if {EIA_COM} >= 140000 Million kilowatt-hours in 2026-12 (source: EIA).")
EIA_COM_GE = {"series": EIA_COM, "comparator": ">=", "threshold": 140000, "observation": "2026-12",
              "units": "Million kilowatt-hours", "transform": ""}


@pytest.fixture
def datacenter() -> dict:
    """The live 2026-10-13 data-centre carrier: EIA retail sales, NSA monthly, 2016-11 to 2026-07."""
    questions = _load("agent_usage/carriers-2026-10-13.json")["questions"]
    return {"schema_version": 1, "series": questions["q2_datacenter"]["series"]}


def _ordinal(day: str) -> int:
    return int(day[:4]) * 12 + int(day[5:7]) - 1


def _changes(row: dict, steps: int, month=None) -> list:
    values = {_ordinal(p["date"]): p["value"] for p in row["observations"] if p["value"] is not None}
    return [values[i + steps] - values[i] for i in values if i + steps in values and month in (None, i % 12)]


def _profile(row: dict, steps: int) -> list:
    """The seasonal-profile sample recomputed independently: the latest calendar month's mean
    h-step change plus every start's deviation from its own month's mean (months with >= 3)."""
    values = {_ordinal(p["date"]): p["value"] for p in row["observations"] if p["value"] is not None}
    pairs = [(i % 12, values[i + steps] - values[i]) for i in sorted(values) if i + steps in values]
    groups = {}
    for month, change in pairs:
        groups.setdefault(month, []).append(change)
    means = {month: sum(group) / len(group) for month, group in groups.items() if len(group) >= 3}
    latest = max(values) % 12
    return [means[latest] + change - means[month] for month, change in pairs if month in means]


def _trimmed(official_data: dict, series: str, keep) -> dict:
    """A copy of a stored carrier whose ``series`` keeps only the observations ``keep`` admits."""
    trimmed = deepcopy(official_data)
    row = next(r for r in trimmed["series"] if r["series"] == series)
    row["observations"] = [point for point in row["observations"] if keep(point["date"])]
    return trimmed


def test_nsa_monthly_base_rate_uses_the_seasonal_profile(datacenter):
    """July-to-December changes of NSA electricity sales: the 9 July starts (median -21,842 million
    kWh) cannot make 30 samples and pooling all 112 starts (median +63) erases the season, so the
    rate adds every start's deviation from its own month's mean to the July mean (n=112)."""
    row = _row(datacenter, EIA_COM)
    assert row["seasonal_adjustment"] == "NSA" and row["observations"][-1]["date"] == "2026-07-01"
    assert fe._empirical_seasonal_share(fe._official_history(row)) >= fe.EMPIRICAL_SEASONAL_SHARE
    july = sorted(_changes(row, 5, month=6))
    assert len(july) == 9 < fe.EMPIRICAL_MIN_SAMPLES and round(july[4]) == -21842
    pooled = sorted(_changes(row, 5))
    assert len(pooled) == 112 and round(fe._empirical_quantile(pooled, 0.5)) == 63
    anchor = validate_data_anchor(dict(EIA_COM_GE), datacenter)
    base = fe.official_empirical_base_rate(row, anchor)
    sample = _profile(row, 5)
    latest = row["observations"][-1]["value"]
    assert (base["n"], base["h"], base["seasonal_basis"]) == (len(sample), 5, "seasonal_profile") == (
        112, 5, "seasonal_profile")
    levels = sorted(round(latest + change, 9) for change in sample)
    assert base["p"] == round(sum(level >= 140000 for level in levels) / 112, 4) == 0.0
    assert base["quantiles"] == {name: round(fe._empirical_quantile(levels, q), 6)
                                 for name, q in (("p10", .1), ("p25", .25), ("p50", .5), ("p75", .75), ("p90", .9))}
    mean = sum(sample) / len(sample)
    sd = math.sqrt(sum((c - mean) ** 2 for c in sample) / (len(sample) - 1))
    assert base["sigma_distance"] == round((140000 - latest) / sd, 2) == -3.22
    # The profile's median change sits with the July starts, not with the season-blind pool.
    assert abs(base["quantiles"]["p50"] - latest - july[4]) < 100
    # Whole years compare a month with itself: no seasonal mixing, no basis.
    whole = fe.official_empirical_base_rate(row, validate_data_anchor({**EIA_COM_GE, "observation": "2030-07"},
                                                                     datacenter))
    assert whole["h"] == 48 and "seasonal_basis" not in whole
    # The fan carries the swing: the July peak falls into the November trough and climbs back,
    # where the pooled fan stayed flat around the latest value.
    fan = fe.official_empirical_fan(row, "2027-08-01")
    assert {p.get("seasonal_basis") for p in fan if p["date"] != "2027-07-01"} == {"seasonal_profile"}
    assert "seasonal_basis" not in next(p for p in fan if p["date"] == "2027-07-01")
    median = {p["date"]: p["p50"] for p in fan}
    assert median["2026-11-01"] < median["2026-12-01"] < latest - 20000 < median["2027-07-01"]
    december = next(p for p in fan if p["date"] == "2026-12-01")
    assert december["n"] == 112 and december["p90"] < 140000 < latest


def test_short_or_unmeasured_nsa_history_pools_the_seasons_and_says_so(datacenter):
    """The seasonal profile needs 5 changes from the latest calendar month and a measured seasonal
    share; without them every start month stays pooled ('all_start_months')."""
    recent = _trimmed(datacenter, EIA_COM, lambda day: day >= "2021-08-01")  # 60 months
    row = _row(recent, EIA_COM)
    history = fe._official_history(row)
    assert len(history) == 60 and fe._empirical_seasonal_share(history) >= fe.EMPIRICAL_SEASONAL_SHARE
    assert len(_changes(row, 5, month=6)) == 4 < fe.EMPIRICAL_PROFILE_LATEST_MIN
    base = fe.official_empirical_base_rate(row, validate_data_anchor(dict(EIA_COM_GE), recent))
    latest = row["observations"][-1]["value"]
    assert (base["n"], base["seasonal_basis"]) == (55, "all_start_months")
    assert base["p"] == round(sum(latest + c >= 140000 for c in _changes(row, 5)) / 55, 4)
    # Septembers before 2024 missing: two August and two September starts leave the seasonal
    # share unmeasured, although a profile sample could be formed from the other months.
    gappy = _trimmed(datacenter, EIA_COM, lambda day: day[5:7] != "09" or day >= "2024-09-01")
    row = _row(gappy, EIA_COM)
    history = fe._official_history(row)
    assert fe._empirical_seasonal_share(history) is None
    assert len(_profile(row, 5)) >= fe.EMPIRICAL_MIN_SAMPLES
    assert fe._empirical_season(row, history, 5) == (None, "all_start_months")
    assert fe.official_empirical_base_rate(row, validate_data_anchor(dict(EIA_COM_GE), gappy))[
        "seasonal_basis"] == "all_start_months"


def test_seasonal_basis_is_absent_for_adjusted_or_unknown_series(carrier):
    unrate = _row(carrier, "fred:UNRATE")  # SA
    assert "seasonal_basis" not in fe.official_empirical_base_rate(unrate, validate_data_anchor(UNRATE_GE5, carrier))
    assert all("seasonal_basis" not in p for p in fe.official_empirical_fan(unrate, "2027-06-01"))
    cbpol = _row(carrier, "bis:WS_CBPOL/M.US")  # adjustment unknown
    assert fe._empirical_season(cbpol, fe._official_history(cbpol), 5) == (None, "")
    yoy = {**_row(_load("forecast_carrier-2026-10-11.json"), "fred:FEDFUNDS"), "transform": "yoy"}
    assert fe._empirical_season(yoy, fe._official_history(yoy), 5) == (None, "")


# FRED's NSA unemployment rate (UNRATENSA) 2016-11 to 2026-09 as published on 2026-10-14: no
# October 2025 value (the federal shutdown), the April 2020 pandemic spike included.
UNRATENSA = (
    "4.4 4.5 5.1 4.9 4.6 4.1 4.1 4.5 4.6 4.5 4.1 3.9 3.9 3.9 4.5 4.4 4.1 3.7 3.6 4.2 4.1 3.9 3.6 3.5 3.5 "
    "3.7 4.4 4.1 3.9 3.3 3.4 3.8 4 3.8 3.3 3.3 3.3 3.4 4 3.8 4.5 14.4 13 11.2 10.5 8.5 7.7 6.6 6.4 6.5 "
    "6.8 6.6 6.2 5.7 5.5 6.1 5.7 5.3 4.6 4.3 3.9 3.7 4.4 4.1 3.8 3.3 3.4 3.8 3.8 3.8 3.3 3.4 3.4 3.3 3.9 "
    "3.9 3.6 3.1 3.4 3.8 3.8 3.9 3.6 3.6 3.5 3.5 4.1 4.2 3.9 3.5 3.7 4.3 4.5 4.4 3.9 3.9 4 3.8 4.4 4.5 "
    "4.2 3.9 4 4.4 4.6 4.5 4.3 4.3 4.1 4.7 4.7 4.3 4 4.1 4.4 4.4 4.3 4"
)


def test_one_shock_does_not_hide_a_seasonal_swing(carrier):
    """The pandemic spike (3.5% to 14.4% in two months) dominated the raw variance of UNRATENSA's
    monthly changes, so its seasonal share read -0.00 and the seasons were pooled without a word;
    on ranks it reads 0.47 and the rate takes the seasonal profile."""
    row = deepcopy(_row(carrier, "fred:UNRATE"))
    months = [m for m in range(2016 * 12 + 10, 2026 * 12 + 9) if m != 2025 * 12 + 9]
    values = [float(v) for v in UNRATENSA.split()]
    assert len(months) == len(values) == 118
    row.update(series="fred:UNRATENSA", seasonal_adjustment="NSA",
               title="Unemployment Rate (Not Seasonally Adjusted)",
               observations=[{"date": f"{m // 12:04d}-{m % 12 + 1:02d}-01", "value": v, "flag": ""}
                             for m, v in zip(months, values)])
    history = fe._official_history(row)
    assert len(history) == 118 and history[-1][1] == "2026-09-01"
    assert round(fe._empirical_seasonal_share(history), 2) == 0.47
    assert fe._empirical_season(row, history, 3) == (None, "seasonal_profile")
    base = fe.official_empirical_base_rate(row, {"comparator": "<", "threshold": 4, "period": "2026-12-01"})
    assert (base["h"], base["seasonal_basis"]) == (3, "seasonal_profile")
    # Rates without a swing keep reading as such on ranks (the stored carriers' NSA policy rates).
    questions = _load("agent_usage/carriers-2026-10-13.json")["questions"]
    for question, series in (("q1_cpi_fed", "fred:FEDFUNDS"), ("q4_ecb_dfr", "fred:ECBDFR"),
                             ("q5_semis", "fred:PCU33443344")):
        rate = _row({"schema_version": 1, "series": questions[question]["series"]}, series)
        assert fe._empirical_seasonal_share(fe._official_history(rate)) < 0.1


@pytest.mark.parametrize("question, series, threshold, statement", [
    ("q1_cpi_fed", "fred:FEDFUNDS", 3, "The US federal funds effective rate is below 3% in March 2027."),
    ("q4_ecb_dfr", "fred:ECBDFR", 2, "The ECB deposit facility rate is below 2% in March 2027."),
])
def test_nsa_series_without_a_seasonal_swing_keep_the_plain_rate(question, series, threshold, statement):
    """FRED publishes policy rates (and the semiconductor PPI) 'Not Seasonally Adjusted' although
    they have no seasonal swing: their rate is the plain pooled sample, disclosed as nothing and
    still the yardstick of the divergence flag, while EIA sales and the euro-area HICP index
    (also NSA, strongly seasonal) take the seasonal profile."""
    questions = _load("agent_usage/carriers-2026-10-13.json")["questions"]
    carrier = {"schema_version": 1, "series": questions[question]["series"]}
    row = _row(carrier, series)
    assert row["seasonal_adjustment"] == "NSA"
    history = fe._official_history(row)
    assert fe._empirical_season(row, history, 6) == (None, "")
    binary = _binary(carrier, statement=statement, probability=0.7,
                     criteria=f"Resolves YES if {series} < {threshold}% in 2027-03 (source: FRED).",
                     anchor={"series": series, "comparator": "<", "threshold": threshold, "observation": "2027-03",
                             "units": "Percent", "transform": ""})
    binary["id"] = "F1"
    base = binary["data_anchor"]["empirical_base_rate"]
    assert (base["n"], base["h"]) == (113, 6) and "seasonal_basis" not in base
    assert [d["id"] for d in fe._binary_quality([binary], min_count=1)["base_rate_divergence"]] == ["F1"]
    assert all("seasonal_basis" not in point for point in fe.official_empirical_fan(row, "2027-03-01"))
    block = fe.official_outside_view_block(carrier, questions[question]["horizon_date"], "English")
    line = next(line for line in block.splitlines() if f"({series})" in line)
    assert "change to the horizon" in line and "pooled" not in line and "seasonal profile" not in line
    ppi = _row({"schema_version": 1, "series": questions["q5_semis"]["series"]}, "fred:PCU33443344")
    assert fe._empirical_season(ppi, fe._official_history(ppi), 5) == (None, "")
    for name, seasonal in (("q2_datacenter", EIA_COM), ("q4_ecb_dfr", "fred:CP0000EZ19M086NEST")):
        nsa = _row({"schema_version": 1, "series": questions[name]["series"]}, seasonal)
        assert fe._empirical_season(nsa, fe._official_history(nsa), 5) == (None, "seasonal_profile")


def test_long_nsa_history_uses_same_calendar_month_starts(datacenter):
    """With 40 years of monthly history the July starts alone make 39 samples."""
    row = deepcopy(_row(datacenter, EIA_COM))
    seasonal = [0, -8, -5, 2, 9, 15, 20, 18, 6, -3, -9, -12]  # calendar-month swing, Jan..Dec
    row["observations"] = [{"date": f"{1986 + (m + 7) // 12:04d}-{(m + 7) % 12 + 1:02d}-01",
                            "value": 1000.0 + m + 10 * seasonal[(m + 7) % 12], "flag": ""} for m in range(480)]
    assert row["observations"][-1]["date"] == "2026-07-01"
    anchor = {"comparator": ">=", "threshold": 1400, "period": "2026-12-01"}
    base = fe.official_empirical_base_rate(row, anchor)
    same = _changes(row, 5, month=6)
    assert (base["n"], base["seasonal_basis"]) == (len(same), "same_calendar_month") == (39, "same_calendar_month")
    latest = row["observations"][-1]["value"]
    assert base["p"] == round(sum(latest + c >= 1400 for c in same) / len(same), 4)
    # Every July-to-December change is +5 - 320 = -315, so the latest 1680 falls to 1365 (< 1400).
    assert base["p"] == 0.0 and base["quantiles"]["p50"] == latest - 315
    assert all(p["seasonal_basis"] == "same_calendar_month" for p in fe.official_empirical_fan(row, "2026-12-01"))


SEASONAL_PROFILE_EN = "same-month seasonal mean plus pooled deviations, not seasonally adjusted"
SEASONAL_PROFILE_ZH = "同月季节均值加合并偏差，未经季节调整"


def test_seasonal_profile_is_disclosed_wherever_the_rate_is_shown(datacenter):
    """The profile keeps the seasons apart, so it is shown with its basis and stays the yardstick of
    the 25 pp divergence flag (a model 40% vs a 0% profile rate is flagged)."""
    from app.services import exec_brief
    binary = _binary(datacenter, statement=EIA_COM_STATEMENT, criteria=EIA_COM_CRITERIA, anchor=EIA_COM_GE,
                     probability=0.4)
    binary["id"] = "F1"
    base = binary["data_anchor"]["empirical_base_rate"]
    assert (base["seasonal_basis"], base["p"]) == ("seasonal_profile", 0.0)
    forecast = {"scenarios": [{"name": "Baseline", "probability": 1.0, "resolution_criteria": "x"}],
                "binary_forecasts": [binary]}
    cell = f"0% (n=112, h=5; {SEASONAL_PROFILE_EN})"
    assert f"| {cell} |" in fe.render_binary_forecasts_block(forecast, "English")
    assert f"0%（n=112，5 期；{SEASONAL_PROFILE_ZH}）" in fe.render_binary_forecasts_block(forecast, "Chinese")
    assert f"| {cell} vs model 40% |" in fe.render_resolution_block(forecast, language="English",
                                                                    official_data=datacenter)
    assert f"0%（n=112，5 期；{SEASONAL_PROFILE_ZH}）vs 模型 40%" in fe.render_resolution_block(
        forecast, language="Chinese", official_data=datacenter)
    assert fe._binary_quality([binary], min_count=1)["base_rate_divergence"] == [
        {"id": "F1", "probability": 0.4, "empirical_p": 0.0, "divergence": 0.4}]
    line = exec_brief._anchor_watch_line(binary, exec_brief._LABELS["en"])[1]
    assert f"historical base rate 0% ({SEASONAL_PROFILE_EN})" in line
    assert f"（{SEASONAL_PROFILE_ZH}）" in exec_brief._anchor_watch_line(binary, exec_brief._LABELS["zh"])[1]
    block = fe.official_outside_view_block(datacenter, "2026-12-31", "English")
    assert "; 5-month change to the horizon 2026-12 (n=112; seasonal profile): p10 " in block
    zh = fe.official_outside_view_block(datacenter, "2026-12-31", "Chinese")
    assert "至预测期末 2026-12 的 5 个月变化经验分位（n=112；同月季节均值）" in zh
    whole = fe.official_outside_view_block(datacenter, "2030-07-31", "English")
    assert "48-month change to the horizon 2030-07 (n=69): p10 " in whole
    assert "seasonal profile" not in whole and "pooled" not in whole
    # A scenario range on the series carries the same basis.
    ranged = fe.validate_metric_range({"series": EIA_COM, "low": 120000, "high": 135000, "period": "2026-12"},
                                      datacenter)
    assert ranged["empirical_base_rate"]["seasonal_basis"] == "seasonal_profile"
    assert ranged["empirical_base_rate"]["n"] == 112 and ranged["empirical_base_rate"]["p"] > 0.8


def test_outside_view_percent_change_uses_the_seasonal_profile(datacenter):
    """The '% change' quantiles of a seasonal-profile line come from the same profile of relative changes."""
    row = _row(datacenter, EIA_COM)
    values = {_ordinal(p["date"]): p["value"] for p in row["observations"] if p["value"] is not None}
    pairs = [(i % 12, (values[i + 5] - values[i]) / abs(values[i])) for i in sorted(values) if i + 5 in values]
    means = {m: sum(c for k, c in pairs if k == m) / sum(1 for k, _c in pairs if k == m) for m in range(12)}
    relative = sorted(means[6] + c - means[m] for m, c in pairs)
    from app.services.official_data import data_api
    api = data_api()
    cells = [api.format_change(round(fe._empirical_quantile(relative, q) * 100, 9), "Percent").replace(" pp", "%")
             for q in (0.1, 0.5, 0.9)]
    line = next(line for line in fe.official_outside_view_block(datacenter, "2026-12-31", "English").splitlines()
                if f"({EIA_COM})" in line)
    assert line.endswith(f"; as % change: p10 {cells[0]}, median {cells[1]}, p90 {cells[2]}.")
    assert cells[1].startswith("-1")  # a ~15% summer-to-winter fall, not the pooled ~0%


def test_pooled_seasons_are_disclosed_and_never_flag_divergence(datacenter):
    """The disclosed fallback (too few July starts in a 60-month history) keeps its caveat and is
    no yardstick for the divergence flag."""
    from app.services import exec_brief
    recent = _trimmed(datacenter, EIA_COM, lambda day: day >= "2021-08-01")
    binary = _binary(recent, statement=EIA_COM_STATEMENT, criteria=EIA_COM_CRITERIA, anchor=EIA_COM_GE,
                     probability=0.1)
    binary["id"] = "F1"
    base = binary["data_anchor"]["empirical_base_rate"]
    assert base["seasonal_basis"] == "all_start_months" and base["p"] - 0.1 > fe._BASE_RATE_DIVERGENCE
    forecast = {"scenarios": [{"name": "Baseline", "probability": 1.0, "resolution_criteria": "x"}],
                "binary_forecasts": [binary]}
    cell = f"{base['p'] * 100:.0f}% (n=55, h=5; start months pooled, not seasonally adjusted)"
    assert f"| {cell} |" in fe.render_binary_forecasts_block(forecast, "English")
    zh_cell = f"{base['p'] * 100:.0f}%（n=55，5 期；合并所有起始月份，未经季节调整）"
    assert zh_cell in fe.render_binary_forecasts_block(forecast, "Chinese")
    assert f"| {cell} vs model 10% |" in fe.render_resolution_block(forecast, language="English",
                                                                    official_data=recent)
    assert "base_rate_divergence" not in fe._binary_quality([binary], min_count=1)
    line = exec_brief._anchor_watch_line(binary, exec_brief._LABELS["en"])[1]
    assert f"historical base rate {base['p'] * 100:.0f}% (start months pooled, not seasonally adjusted)" in line
    assert "（合并所有起始月份，未经季节调整）" in exec_brief._anchor_watch_line(binary, exec_brief._LABELS["zh"])[1]
    block = fe.official_outside_view_block(recent, "2026-12-31", "English")
    assert "; 5-month change to the horizon 2026-12 (n=55; seasons pooled): p10 " in block
    zh = fe.official_outside_view_block(recent, "2026-12-31", "Chinese")
    assert "至预测期末 2026-12 的 5 个月变化经验分位（n=55；合并各起始月份）" in zh



# ----------------------------------------------------------------- tables (RPT-15)


def test_part1_base_rate_column_only_when_an_anchor_has_one(carrier):
    anchored = _binary(carrier)
    anchored["id"] = "F1"
    block = fe.render_binary_forecasts_block({"binary_forecasts": [anchored]}, "English")
    assert "| Official-data base rate |" in block and "| 9% (n=108, h=9) |" in block
    plain = {**anchored}
    plain.pop("data_anchor")
    block = fe.render_binary_forecasts_block({"binary_forecasts": [plain]}, "English")
    assert "base rate" not in block
    zh = fe.render_binary_forecasts_block({"binary_forecasts": [anchored]}, "Chinese")
    assert "官方数据经验基率" in zh and "9%（n=108，9 期）" in zh


def test_watch_table_uses_carrier_values_one_format_and_source_tags(carrier):
    bundle = _load("report_bundle-2026-10-11.json")
    index = {f"S{i}": source for i, source in enumerate(bundle["sources"], 1)}
    debt = {"series": "usgov:treasury/debt_to_penny", "comparator": ">", "threshold": 45e12,
            "observation": "2027-12", "units": "U.S. dollars"}
    binaries = [_binary(carrier, probability=0.3),
                _binary(carrier, statement="US public debt exceeds $45 trillion in December 2027",
                        criteria="usgov:treasury/debt_to_penny > 45000000000000 U.S. dollars in 2027-12",
                        anchor=debt, probability=0.55)]
    binaries[0]["data_anchor"]["latest_value"] = 999  # model-transcribed values never reach the table
    scenarios = [{"name": "Baseline", "probability": 1.0, "resolution_criteria": "x"}]
    block = fe.render_resolution_block({"scenarios": scenarios, "binary_forecasts": binaries}, language="English",
                                       official_data=carrier, source_index=index)
    rows = block.split("### Official series to watch")[1].strip().splitlines()[2:]
    assert rows[0] == ("| Unemployment Rate — United States (fred:UNRATE) | 4.2% (2026-09) | >= 5% / 2027-06 | "
                       "9% (n=108, h=9) vs model 30% | [Source](<https://fred.stlouisfed.org/series/UNRATE>) [S1] |")
    assert rows[1].startswith("| Debt to the Penny: Total Public Debt Outstanding — United States "
                              "(usgov:treasury/debt_to_penny) | 40093219044989.21 U.S. dollars "
                              "(≈ 40.09 trillion U.S. dollars) (2026-09) | > 45000000000000 U.S. dollars "
                              "(≈ 45 trillion U.S. dollars) / 2027-12 | insufficient history vs model 55% |")
    assert "999" not in block and "e+13" not in block
    zh = fe.render_resolution_block({"scenarios": scenarios, "binary_forecasts": binaries}, language="Chinese",
                                    official_data=carrier)
    assert "| 美国失业率（fred:UNRATE） | 4.2%（2026-09） | >= 5% / 2027-06 | 9%（n=108，9 期）vs 模型 30% |" in zh


# ------------------------------------------- automatic resolution (resolution monitor)

DEBT_GT45T = {"series": "usgov:treasury/debt_to_penny", "comparator": ">", "threshold": 45e12,
              "observation": "2027-12", "units": "U.S. dollars"}
WDI_LT0 = {"series": "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", "comparator": "<", "threshold": 0, "observation": "2027"}


@pytest.mark.parametrize("anchor, statement, criteria, auto", [
    (UNRATE_GE5, STATEMENT, CRITERIA, True),
    (FUNDS_LT3, "The effective federal funds rate is below 3% in December 2027", "fred:FEDFUNDS < 3% in 2027-12",
     True),
    # Daily data averaged or sampled to months.
    (SPREAD_LT0, "The 10-year minus 3-month Treasury spread < 0% in June 2027", SPREAD_CRITERIA, False),
    (DEBT_GT45T, "US public debt exceeds $45 trillion in December 2027",
     "usgov:treasury/debt_to_penny > 45000000000000 U.S. dollars in 2027-12", False),
    # World Bank Data360 strips observation status.
    (WDI_LT0, "US GDP growth is negative in 2027", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA < 0% in 2027", False),
])
def test_admitted_anchor_says_whether_the_monitor_can_settle_it(carrier, anchor, statement, criteria, auto):
    binary = _binary(carrier, statement=statement, criteria=criteria, anchor=anchor, probability=0.4)
    assert binary["data_anchor"]["auto_resolvable"] is auto
    assert binary["probability"] == 0.4
    assert validate_data_anchor(binary["data_anchor"], carrier)["series"] == anchor["series"]


def _anchor_periods(row: dict) -> list:
    frequency = row["frequency"]
    periods = []
    for point in row["observations"]:
        if point["value"] is None:
            continue
        day = point["date"]
        periods.append(day[:7] if frequency == "M" else
                       f"{day[:4]}-Q{(int(day[5:7]) - 1) // 3 + 1}" if frequency == "Q" else day)
    return periods


@pytest.mark.parametrize("source", [
    "forecast_carrier-2026-10-11.json", "forecast_history_v3-2026-10-11.json", "usgov_spending_total_fy",
    "wb_gep_gdp_growth_chn_default_window", "wb_imf_weo_ngdpd_usa", "imf_weo_usa_ngdp_rpch_default_window",
    "imf_pcps_poilbre_2024", "bis_ws_cbpol_us_2024", "bis_ws_tc_us_770", "fred_dgs10_daily",
    "fred_dfedtaru_daily_step", "fred_unrate_2024", "usgov_debt_to_penny_daily", "usgov_mts_deficit_2024",
])
def test_auto_resolvable_agrees_with_the_data_layer_resolver(source, tmp_path):
    """Every stored period of a flagged series resolves 'manual'; an unflagged one settles."""
    from app.services.official_data import resolve_data_anchor
    official_data = (_load(source) if source.endswith(".json")
                     else {"schema_version": 1, "series": [_replayed(source, tmp_path)]})
    rows = fe.official_series_rows(official_data)
    assert rows
    for row in rows:
        statuses = set()
        for period in _anchor_periods(row):
            anchor = validate_data_anchor({"series": row["series"], "comparator": ">", "threshold": 0,
                                           "observation": period}, official_data)
            statuses.add(resolve_data_anchor(anchor, row, as_of="2031-01-01")["status"])
        if fe.official_auto_resolvable(row):
            assert "resolved" in statuses, row["series"]
        else:
            assert statuses == {"manual"}, row["series"]


def test_unsettleable_anchor_still_feeds_the_watch_table(carrier):
    binary = _binary(carrier, statement="The 10-year minus 3-month Treasury spread < 0% in June 2027",
                     criteria=SPREAD_CRITERIA, anchor=SPREAD_LT0, probability=0.25)
    assert binary["data_anchor"]["auto_resolvable"] is False
    forecast = {"scenarios": [{"name": "Baseline", "probability": 1.0, "resolution_criteria": "x"}],
                "binary_forecasts": [binary]}
    rows = fe.render_resolution_block(forecast, language="English", official_data=carrier).split(
        "### Official series to watch")[1].strip().splitlines()[2:]
    assert len(rows) == 1 and "(fred:T10Y3M) |" in rows[0] and "| < 0% / 2027-06 |" in rows[0]


# ------------------------------------------------- RPT-6 / MISSED-2 / downstream M1


def test_policy2_daily_months_complete_only_when_fully_covered(carrier):
    row = _row(carrier, "fred:DGS10")
    kinds = dict(zip((p["date"] for p in row["observations"]), fe.official_observation_kinds(row)))
    assert kinds["2024-10-01"] == "partial-period value"  # coverage starts 2024-10-11
    assert kinds["2026-10-01"] == "partial-period value"  # month in progress at retrieval
    assert kinds["2026-09-01"] == "historical observation"
    assert fe.official_latest_observed(row) == {"date": "2026-09-01", "value": 4.989047619047619}
    stored = row["provenance"]["periods"]["2026-09-01"]
    assert stored["complete"] is False  # the stored row itself is unchanged


def test_current_policy_wdi_history_is_observed_and_anchors(history, carrier):
    row = _row(history, "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA")
    assert set(fe.official_observation_kinds(row)) == {"historical observation"}
    anchor = {"series": row["series"], "comparator": ">=", "threshold": 2, "observation": "2026",
              "units": row["units"]}
    binary = _binary(history, statement="US GDP growth is at least 2% in 2026",
                     criteria=f"{row['series']} >= 2% in 2026 (source: World Bank)", anchor=anchor)
    assert binary["data_anchor"]["latest_value"] == 2.161382
    assert binary["data_anchor"]["empirical_base_rate"]["n"] == 35
    legacy = _row(carrier, "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA")
    assert set(fe.official_observation_kinds(legacy)) == {"unclassified publisher value"}


def test_weo_gep_status_uses_exact_prefixes(tmp_path):
    from official_data_replay import stored_row
    gep_named = stored_row("fred_gepucurrent_stored")
    assert gep_named["series"] == "fred:GEPUCURRENT"
    assert set(fe.official_observation_kinds(gep_named)) == {"historical observation"}
    gep = _replayed("wb_gep_gdp_growth_chn_default_window", tmp_path)
    assert fe.official_observation_kinds(gep) == ["historical observation"] * 2 + [
        "publisher estimate"] + ["publisher projection"] * 2


# --------------------------------------------------------------- RPT-9 metric_range


@pytest.mark.parametrize("value", [
    {"series": "fred:UNRATE", "low": 4.5, "high": 5.5, "period": "2027-06", "units": "Percent"},
    {"series": "fred:UNRATE", "low": None, "high": 4.5, "period": "2027-06", "units": "%"},
    {"series": "fred:UNRATE", "low": 5.5, "high": None, "observation": "2027-06-01"},
])
def test_metric_range_validates_against_the_carrier(carrier, value):
    result = fe.validate_metric_range(value, carrier)
    assert result["series"] == "fred:UNRATE" and result["period"] == "2027-06-01"
    assert result["frequency"] == "M" and result["units"] == "Percent"
    base = result["empirical_base_rate"]
    assert base["n"] == 108 and base["h"] == 9 and 0 <= base["p"] <= 1


@pytest.mark.parametrize("value", [
    {"series": "fred:UNRATE", "low": 5.5, "high": 4.5, "period": "2027-06"},
    {"series": "fred:UNRATE", "low": None, "high": None, "period": "2027-06"},
    {"series": "fred:UNRATE", "low": True, "high": 5, "period": "2027-06"},
    {"series": "fred:UNRATE", "low": float("nan"), "high": 5, "period": "2027-06"},
    {"series": "fred:UNRATE", "low": 4, "high": 5, "period": "2027-13"},
    {"series": "fred:UNRATE", "low": 4, "high": 5, "period": "2027-06", "units": "Percentage points"},
    {"series": "fred:NOTCARRIED", "low": 4, "high": 5, "period": "2027-06"},
    "fred:UNRATE 4-5%",
])
def test_invalid_metric_ranges_are_dropped(carrier, value):
    assert fe.validate_metric_range(value, carrier) is None


def test_annual_negative_range_validates_with_its_outside_view(history):
    result = fe.validate_metric_range({"series": "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", "low": -3, "high": 0,
                                       "period": "2026", "units": "%"}, history)
    assert (result["low"], result["high"], result["period"], result["frequency"]) == (-3.0, 0.0, "2026-01-01", "A")
    assert result["empirical_base_rate"]["n"] == 35 and result["empirical_base_rate"]["h"] == 1


@pytest.mark.parametrize("text, low, high", [
    ("GDP annual growth between -3% and 0% in 2027", -3.0, 0.0),
    ("GDP annual growth between −3% and −1% in 2027", -3.0, -1.0),
])
def test_prose_ranges_accept_signed_bounds(text, low, high):
    interval = fe._extract_comparable_numeric_range(text)
    assert (interval["low"], interval["high"], interval["scope"]) == (low, high, "2027")


def _spine_reply():
    return {"scenarios": [
        {"name": "Soft landing", "probability": 0.5, "resolution_criteria": "UNRATE below 4.5% in 2027-06",
         "metric_range": {"series": "fred:UNRATE", "low": None, "high": 4.5, "period": "2027-06", "units": "%"}},
        {"name": "Recession", "probability": 0.5, "resolution_criteria": "UNRATE above 5.5% in 2027-06",
         "metric_range": {"series": "fred:NOTCARRIED", "low": 5.5, "high": None, "period": "2027-06"}},
    ], "confidence": "medium"}


def test_spine_keeps_only_validated_metric_ranges_and_adds_outside_view(carrier):
    llm = FakeLLMClient(json_responses=[_spine_reply()])
    spine = fe.derive_forecast_spine(llm, central_question="US labour market", horizon="2027-12-31",
                                     quantitative_facts="fred:UNRATE 4.2% (2026-09) [S1]", official_data=carrier,
                                     language="English")
    soft, recession = spine["scenarios"]
    assert soft["metric_range"]["series"] == "fred:UNRATE" and soft["metric_range"]["high"] == 4.5
    assert soft["metric_range"]["empirical_base_rate"]["n"] == 108
    assert "metric_range" not in recession
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "[Official history — outside view" in prompt and "metric_range" in prompt


def test_spine_prompt_and_output_unchanged_without_official_data():
    plain = FakeLLMClient(json_responses=[_spine_reply()])
    spine = fe.derive_forecast_spine(plain, central_question="US labour market", horizon="2027-12-31")
    omitted = FakeLLMClient(json_responses=[_spine_reply()])
    fe.derive_forecast_spine(omitted, central_question="US labour market", horizon="2027-12-31",
                             official_data=None)
    prompt = plain.calls[0]["messages"][0]["content"]
    assert prompt == omitted.calls[0]["messages"][0]["content"]
    assert "metric_range" not in prompt and "outside view" not in prompt and "官方历史" not in prompt
    assert all("metric_range" not in s for s in spine["scenarios"])


def test_critique_keeps_validated_ranges_by_name_and_cannot_invent_them(carrier):
    forecast = {"scenarios": [{"name": "Soft landing", "probability": 0.6, "resolution_criteria": "x",
                               "metric_range": fe.validate_metric_range(
                                   {"series": "fred:UNRATE", "low": None, "high": 4.5, "period": "2027-06"},
                                   carrier)},
                              {"name": "Recession", "probability": 0.4, "resolution_criteria": "y"}],
                "confidence": "medium"}
    reply = {"scenarios": [{"name": "Soft landing", "probability": 0.5, "resolution_criteria": "x"},
                           {"name": "Recession", "probability": 0.5, "resolution_criteria": "y",
                            "metric_range": {"series": "fred:UNRATE", "low": 9, "high": None,
                                             "period": "2027-06"}}]}
    llm = FakeLLMClient(json_responses=[reply])
    out = fe.self_critique_forecast(forecast, llm, data_pack="fred:UNRATE 4.2% (2026-09) [S1]")
    assert out["scenarios"][0]["metric_range"] == forecast["scenarios"][0]["metric_range"]
    assert "metric_range" not in out["scenarios"][1]
    assert llm.calls[0]["messages"][0]["content"].endswith("fred:UNRATE 4.2% (2026-09) [S1]")
    bare = FakeLLMClient(json_responses=[reply])
    fe.self_critique_forecast(forecast, bare)
    assert "官方统计数据" not in bare.calls[0]["messages"][0]["content"]


# ------------------------------------------------ US federal fiscal years (FE-N1)

SPENDING = "usgov:spending/total"
SPENDING_GT = {"series": SPENDING, "comparator": ">", "threshold": 7e12, "observation": "2025-10-01"}
SPENDING_CRITERIA = f"Resolves YES if {SPENDING} > 7000000000000 U.S. dollars in FY2026 (source: USAspending)."


@pytest.fixture
def spending(tmp_path) -> dict:
    """The real USAspending capture replayed: fiscal years FY2023-FY2027 stored at their start
    dates (2022-10-01 ... 2026-10-01) with 'us_federal_fiscal_year' period records."""
    return {"schema_version": 1, "series": [_replayed("usgov_spending_total_fy", tmp_path)]}


@pytest.mark.parametrize("statement, criteria, admitted", [
    ("US federal award spending exceeds $7 trillion in FY2026.", SPENDING_CRITERIA, True),
    ("US federal award spending exceeds $7 trillion in FY 2026.",
     f"Resolves YES if {SPENDING} > 7000000000000 U.S. dollars for 2025-10-01 (source: USAspending).", True),
    ("US federal award spending exceeds $7 trillion in fiscal year 2026.", SPENDING_CRITERIA, True),
    ("美国联邦奖励支出在2026财年超过7万亿美元。", f"若 {SPENDING} 在 FY2026 > 7000000000000 U.S. dollars 则为是。", True),
    # A calendar year is not the fiscal year: 2025 is FY2025's last and FY2026's first quarter (this anchored).
    ("US federal award spending exceeds $7 trillion in 2025.",
     f"Resolves YES if {SPENDING} > 7000000000000 U.S. dollars in 2025 (source: USAspending).", False),
    ("US federal award spending exceeds $7 trillion in 2026.", SPENDING_CRITERIA, False),
    ("US federal award spending exceeds $7 trillion in FY2025.", SPENDING_CRITERIA, False),
    ("US federal award spending exceeds $7 trillion in FY2026.",
     f"Resolves YES if {SPENDING} > 7000000000000 U.S. dollars in FY2025 (source: USAspending).", False),
])
def test_fiscal_year_anchor_is_named_by_its_fiscal_year(spending, statement, criteria, admitted):
    """The anchored period 2025-10-01 of a fiscal-year series is FY2026 (Oct 2025 - Sep 2026)."""
    row = spending["series"][0]
    assert row["provenance"]["periods"]["2025-10-01"]["label"] == "FY2026"
    binary = fe._normalize_binaries([{"statement": statement, "probability": 0.3, "resolution_criteria": criteria,
                                      "data_anchor": dict(SPENDING_GT)}], official_data=spending)[0]
    assert ("data_anchor" in binary) is admitted, statement


@pytest.mark.parametrize("observation, period", [
    ("FY2026", "2025-10-01"), ("FY 2026", "2025-10-01"), ("2025-10-01", "2025-10-01"),
    # A calendar year, an unstored fiscal year or a two-digit label never names a fiscal period.
    ("2026", None), ("FY2031", None), ("FY26", None),
])
def test_fiscal_year_anchor_accepts_its_stored_fy_label(spending, observation, period):
    """RPT-R3-4: the prompt shows FY labels, so 'FY2026' must validate to the stored period start."""
    from app.services.official_data import validate_data_anchor
    anchor = validate_data_anchor({**SPENDING_GT, "observation": observation}, spending)
    assert (anchor or {}).get("period") == period
    if period:
        binary = fe._normalize_binaries([{"statement": "US federal award spending exceeds $7 trillion in FY2026.",
                                          "probability": 0.3, "resolution_criteria": SPENDING_CRITERIA,
                                          "data_anchor": {**SPENDING_GT, "observation": observation}}],
                                        official_data=spending)[0]
        assert binary["data_anchor"]["period"] == "2025-10-01"
        assert binary["resolution_criteria"].endswith("for FY2026.")


def test_fiscal_year_anchor_reads_its_fy_label_everywhere(spending, tmp_path):
    from app.services import exec_brief
    from app.services import report_visualizer as rv
    row = spending["series"][0]
    raw = {"statement": "US federal award spending exceeds $7 trillion in FY2026.", "probability": 0.3,
           "resolution_criteria": SPENDING_CRITERIA, "data_anchor": dict(SPENDING_GT)}
    binary = fe._normalize_binaries([raw], official_data=spending)[0]
    anchor = binary["data_anchor"]
    assert anchor["period"] == "2025-10-01"
    assert binary["resolution_criteria"].endswith(
        "Official resolution: usgov:spending/total > 7000000000000 U.S. dollars (≈ 7 trillion U.S. dollars) for FY2026.")
    zh = fe._normalize_binaries([raw], official_data=spending, language="Chinese")[0]
    assert zh["resolution_criteria"].endswith("，观察期 FY2026。")
    # Re-normalizing a stored forecast strips its own settlement clause and keeps the anchor.
    again = fe._normalize_binaries([{k: binary[k] for k in raw}], official_data=spending)[0]
    assert again["data_anchor"]["period"] == "2025-10-01"
    assert again["resolution_criteria"] == binary["resolution_criteria"]
    binary["id"] = "F1"
    forecast = {"scenarios": [{"name": "Baseline", "probability": 1.0, "resolution_criteria": "x"}],
                "binary_forecasts": [binary]}
    watch = fe.render_resolution_block(forecast, language="English", official_data=spending)
    assert "| > 7000000000000 U.S. dollars (≈ 7 trillion U.S. dollars) / FY2026 |" in watch
    # The executive brief reads the report's stored rows for the label.
    line = exec_brief._anchor_watch_line(binary, exec_brief._LABELS["en"], {SPENDING: row})[1]
    assert line.endswith("threshold > 7000000000000 U.S. dollars (≈ 7 trillion U.S. dollars) (FY2026)")
    assert exec_brief._build_watch_block(forecast, exec_brief._LABELS["zh"], rows={SPENDING: row}).endswith(
        "阈值 > 7000000000000 U.S. dollars（≈7万亿美元） (FY2026)")
    folder = tmp_path / "report"
    folder.mkdir()
    canonical = json.dumps(spending, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib
    (folder / "official_data.json").write_text(json.dumps({
        "schema_version": 1, "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "source_tags": {SPENDING: "S1"}, "official_data": spending}), encoding="utf-8")
    assert exec_brief._official_rows(str(folder)) == {SPENDING: row}
    assert exec_brief._official_rows(str(tmp_path / "missing")) == {}
    (folder / "full_report.md").write_text("# Federal spending\n\nAnalysis.\n", encoding="utf-8")
    (folder / "forecast.json").write_text(json.dumps(forecast), encoding="utf-8")
    brief = exec_brief.ExecBriefBuilder.build("report_fy", str(folder), force=True)["exec_brief"]
    assert "threshold > 7000000000000 U.S. dollars (≈ 7 trillion U.S. dollars) (FY2026)" in Path(brief).read_text(
        encoding="utf-8")
    # Chart legend labels of the threshold and of a scenario range on the same fiscal year.
    label = rv.ReportVisualizer._official_threshold_label({**anchor, "probability": 0.3, "empirical_base_rate": None},
                                                          row["units"], row)
    assert label.startswith("Model threshold > 7 trillion U.S. dollars (FY2026); P(yes)=30%")
    band = fe.validate_metric_range({"series": SPENDING, "low": 5e12, "high": 6e12, "period": "2025-10-01"}, spending)
    assert rv.ReportVisualizer._official_band_label({**band, "name": "Flat", "probability": 0.4}, row) == (
        "Model scenario: Flat — FY2026 (P=40%)")
    # A fiscal year not stored yet takes the data layer's rule; calendar rows are untouched.
    assert fe.official_fiscal_label(row, "2027-10-01") == "FY2028"
    assert fe.official_anchor_period_text(row, "2027-10-01", "A") == "FY2028"
    assert fe.official_fiscal_label(row, "2027-01-01") == ""
    wdi = _row(_load("forecast_history_v3-2026-10-11.json"), "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA")
    assert fe.official_anchor_period_text(wdi, "2026-01-01", "A") == "2026"
    assert fe.official_anchor_period_text(None, "2026-12-01", "M") == "2026-12"
