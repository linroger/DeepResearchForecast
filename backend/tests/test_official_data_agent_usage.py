"""How forecast, report and simulation agents are shown official data (agent-usage audit).

tests/fixtures/data_sources/real/agent_usage/carriers-2026-10-13.json holds six live
carriers fetched through the data layer for six forecasting questions (US CPI and the
Fed, US data-center electricity, China NEV share, the ECB deposit rate, global
semiconductor sales and, in Chinese, China's 2027 GDP growth): FRED, BIS, World Bank
Data360 (IMF WEO, GEP, WDI), IMF PCPS and usgov EIA/BEA rows with values, statuses,
periods and daily-aggregation provenance verbatim. Each test writes a carrier through
the data layer (write_dataset_files) and reads it back with load_official_data, as a
real run does, then renders the prompt an agent actually receives.

Covered: the report data pack (reader periods, publisher estimates and projections
through the horizon, how daily data became monthly, Chinese wording, room for every
series, the amount behind a value stored in thousands or millions), the outside view
(the window each quantile describes) in critique / pre-mortem / fallback extraction and
in calibration and indicator sections (with how to quote it), the outline relevance
rule, the spine facts slice, the binary-extraction prompt (one snapshot header,
mandatory anchors, how to name the metric, month-end and end-of-period anchoring), the
anchors each question's core binaries can carry (EIA units with a scale word, annual
years ending a sentence, 增速 for 增长率, a provider name with digits, a FRED series
stored without a geography, catalog keywords in natural word order and number, inflation
expectations kept apart from inflation), the stored-series check of report claims in those units,
and the simulation world brief, which used to leave the official snapshot no room at
all and now gives its few rows to every clause the question names. Without official
data every touched prompt is unchanged.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import report_agent as ra
from app.services.official_data import data_api, load_official_data, research_run_window
from app.services.report_agent import ReportAgent, ReportManager
from app.services.simulation_config_generator import SimulationConfigGenerator
from tests.conftest import FakeLLMClient

CARRIERS = (Path(__file__).parent / "fixtures" / "data_sources" / "real" / "agent_usage"
            / "carriers-2026-10-13.json")
FLAGS = {"PREDICTION_MARKETS_ENABLED": False, "REPORT_FORECAST_SELF_CRITIQUE": True,
         "REPORT_PREMORTEM": True, "SIM_WORLD_BRIEF": True, "SIM_MARKET_PRIORS": True}
MARKETS = [{"question": f"Will market question {i} about the forecast topic resolve YES by year-end?",
            "implied_yes_prob": 0.1 * i, "relevance_score": 1 - 0.1 * i, "volume": 1000 * i}
           for i in range(1, 6)]
OUTSIDE_VIEW = {"English": "[Official history — outside view", "Chinese": "【官方历史·外部视角"}


def _questions():
    return json.loads(CARRIERS.read_text(encoding="utf-8"))["questions"]


QUESTIONS = _questions()


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name, value in FLAGS.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "sims"))
    monkeypatch.setattr(ReportAgent, "_define_tools", lambda self: {})
    monkeypatch.setattr(ReportAgent, "_locate_timeline", lambda self: None)
    monkeypatch.setattr(ReportAgent, "_locate_handoff_dir", lambda self: None)

    from app.services import official_data as adapter

    def forbidden(*args, **kwargs):
        pytest.fail("an agent prompt attempted to fetch official data")
    monkeypatch.setattr(adapter, "get_data_sources", forbidden)
    return tmp_path


def _handoff(tmp_path, key):
    """The question's carrier written and read back as a real research run stores it."""
    question = QUESTIONS[key]
    api = data_api()
    handoff = tmp_path / key / "handoff"
    handoff.mkdir(parents=True)
    citations = {source["dataset"]["series"]: f"S{index}"
                 for index, source in enumerate(question["sources"], 1) if source.get("dataset")}
    api.write_dataset_files([api.Series.from_dict(row) for row in question["series"]], handoff,
                            citations=citations)
    cited = " ".join(f"[{tag}]" for tag in citations.values())
    (handoff / "research_report.md").write_text(
        f"# Research dossier\n\n{question['question']}\n\nOfficial statistics used: {cited}.\n", encoding="utf-8")
    (handoff / "sources.json").write_text(json.dumps(question["sources"], ensure_ascii=False), encoding="utf-8")
    (handoff / "meta.json").write_text(json.dumps(question["research_window"]), encoding="utf-8")
    carrier = load_official_data(handoff)
    assert [row["series"] for row in carrier["series"]] == [row["series"] for row in question["series"]]
    return handoff, carrier


def _agent(monkeypatch, key, carrier, model=None):
    question = QUESTIONS[key]
    monkeypatch.setenv("REPORT_OUTPUT_LANGUAGE", question["language"])
    return ReportAgent("g_agent_usage", "sim_agent_usage", question["question"],
                       llm_client=model or FakeLLMClient(), zep_tools=FakeLLMClient(),
                       sources=question["sources"], official_data=carrier)


def _calendar_horizon(tmp_path, key):
    sim = tmp_path / "sims" / "sim_agent_usage"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "simulation_config.json").write_text(json.dumps(
        {"temporal_config": {"mode": "calendar", "horizon_date": QUESTIONS[key]["horizon_date"]}}))


def _prompt(model, index=0):
    return "\n\n".join(str(message.get("content", "")) for message in model.calls[index]["messages"])


# ------------------------------------------------------------- the report data pack


def test_pack_shows_publisher_estimates_and_projections_through_the_horizon(env, monkeypatch):
    """A WEO/GEP row lists its publisher values oldest first (the horizon year
    included), labelled as estimate or projection; before only the last (2031) showed."""
    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    pack = _agent(monkeypatch, "q1_cpi_fed", carrier)._data_pack
    assert ("| All Items, Consumer price index (CPI), Period average, percent change: United States "
            "(wb:IMF_WEO_PCPIPCH/USA) | 2.952% / 2024 | Percent change / A / unknown | [S6] |") in pack
    assert ("Publisher values, not observed history: 2025 2.73% (publisher estimate); 2026 3.228% "
            "(publisher projection); 2027 2.141% (publisher projection); 2028 2.184% (publisher projection); "
            "2029 2.188% (publisher projection); 2030 2.19% (publisher projection); 2031 2.184% "
            "(publisher projection) [S6]") in pack
    assert "Attribute a publisher value to its publisher as a projection or estimate" in pack

    _handoff_dir, carrier = _handoff(env, "q6_china_gdp_zh")
    zh = _agent(monkeypatch, "q6_china_gdp_zh", carrier)._data_pack
    assert ("发布方数值（非观测历史）：2025 4.959%（发布方估计值）；2026 4.413%（发布方预测值）；"
            "2027 4.033%（发布方预测值）；2028 4%（发布方预测值）；2029 3.665%（发布方预测值）；"
            "2030 3.348%（发布方预测值）；2031 3.291%（发布方预测值） [S4]") in zh
    assert "发布方数值（非观测历史）：2024 4.9%（发布方估计值）；2025 4.5%（发布方预测值）；2026 4%（发布方预测值） [S5]" in zh


def test_long_publisher_paths_keep_the_horizon_year():
    path = [{"period": str(year), "kind": "publisher projection"} for year in range(2025, 2037)]
    shown = ra._official_path_points(path, "2030")
    assert [point and point["period"] for point in shown] == [
        "2025", "2026", "2027", None, "2030", None, "2035", "2036"]
    assert [point and point["period"] for point in ra._official_path_points(path)] == [
        "2025", "2026", "2027", None, "2035", "2036"]
    quarters = [{"period": f"{year}-Q{q}", "kind": "publisher projection"} for year in (2026, 2027, 2028)
                for q in range(1, 5)]
    assert [point and point["period"] for point in ra._official_path_points(quarters, "2027")] == [
        "2026-Q1", "2026-Q2", "2026-Q3", None, "2027-Q1", "2027-Q2", "2027-Q3", "2027-Q4", None,
        "2028-Q3", "2028-Q4"]
    assert ra._official_path_points(path[:8], "2030") == path[:8]


def test_pack_says_how_daily_data_became_monthly_and_gives_the_latest_daily_value(env, monkeypatch):
    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    pack = _agent(monkeypatch, "q1_cpi_fed", carrier)._data_pack
    assert ("| Federal Funds Target Range - Upper Limit — United States (fred:DFEDTARU) | 4% / 2026-09 | "
            "Percent / M / NSA | [S8] |\nMonthly values are the end-of-month value of daily data; "
            "latest daily value 4% on 2026-10-13 [S8]\n") in pack
    assert ("(fred:T10YIE) | 2.351% / 2026-09 | Percent / M / NSA | [S11] |\nMonthly values are the monthly "
            "mean of daily data; latest daily value 2.33% on 2026-10-09 [S11]\n") in pack

    _handoff_dir, carrier = _handoff(env, "q4_ecb_dfr")
    pack = _agent(monkeypatch, "q4_ecb_dfr", carrier)._data_pack
    assert ("| ECB Deposit Facility Rate for Euro Area (fred:ECBDFR) | 2.375% / 2026-09 | Percent / M / NSA | "
            "[S4] |\nMonthly values are the monthly mean of daily data; latest daily value 2.5% on 2026-10-13 "
            "[S4]\n") in pack
    # A native monthly series has no aggregation line.
    assert "(bis:WS_CBPOL/M.XM) | 2.5% / 2026-09 | Per cent per year / M / unknown | [S5] |\nYear-over-year" in pack


def test_pack_periods_read_at_the_series_frequency(env, monkeypatch):
    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    pack = _agent(monkeypatch, "q1_cpi_fed", carrier)._data_pack
    assert "| Unemployment Rate — United States (fred:UNRATE) | 4.2% / 2026-09 | Percent / M / SA | [S12] |" in pack
    assert "Historical five-year range in stored window: 3.4% (2023-04) to 4.7% (2021-09) [S12]" in pack
    assert "2026-09-01" not in pack and "2023-04-01" not in pack
    _handoff_dir, carrier = _handoff(env, "q2_datacenter")
    pack = _agent(monkeypatch, "q2_datacenter", carrier)._data_pack
    assert "(usgov:bea/value_added_by_industry/514) | 694.7 / 2026-Q2 |" in pack
    assert "Historical five-year range in stored window: 364.5 (2021-Q2) to 694.7 (2026-Q2) [S10]" in pack


def test_chinese_report_pack_reads_in_chinese(env, monkeypatch):
    _handoff_dir, carrier = _handoff(env, "q6_china_gdp_zh")
    pack = _agent(monkeypatch, "q6_china_gdp_zh", carrier)._data_pack
    lines = pack.split("\n")
    assert lines[0] == "[Official data snapshot / 官方数据快照]"
    assert lines[1].startswith("已存储的官方观测值（撰写时从不重新抓取）。") and "发布方数值须归于发布方" in lines[1]
    assert lines[2] == "| 序列 | 最新历史值 / 期间 | 单位 / 频率 / 调整 | 来源 |"
    assert ("| 中国实际GDP增长率（IMF WEO） (wb:IMF_WEO_NGDP_RPCH/CHN) | 5.003% / 2024 | Percent change / 年度 / 未知 "
            "| [S4] |") in pack
    assert "同比变化：-0.374 个百分点 [S4]" in pack
    assert "存储窗口内五年历史区间：2.337%（2020）至 8.556%（2021）[S4]" in pack
    for english in ("Year-over-year change", "Historical five-year range", "Publisher values",
                    "Stored official observations", "| Series |"):
        assert english not in pack, english


@pytest.mark.parametrize("key", sorted(QUESTIONS))
def test_every_stored_series_fits_the_pack(env, monkeypatch, key):
    """The 5000-character pack keeps every series of each live question whole
    (the 3500 budget dropped rows of the CPI/Fed and data-center questions)."""
    _handoff_dir, carrier = _handoff(env, key)
    pack = _agent(monkeypatch, key, carrier)._data_pack
    assert len(pack) <= 5000
    for row in carrier["series"]:
        assert f"({row['series']}) |" in pack, row["series"]
    assert "not shown" not in pack and "未列出" not in pack


def test_values_stored_in_thousands_or_millions_carry_the_amount_they_stand_for(env, monkeypatch):
    """58522249 Thousands of U.S. Dollars is $58.5 billion: beside a $1 trillion question the agents'
    pack says so (data_sources.scaled_value leaves units that carry a scale word alone)."""
    _handoff_dir, carrier = _handoff(env, "q5_semis")
    pack = _agent(monkeypatch, "q5_semis", carrier)._data_pack
    assert ("(fred:AIES334413RCTUS) | 58522249 (≈ 58.52 billion U.S. Dollars) / 2024 | Thousands of U.S. Dollars "
            "/ A / NSA | [S4] |\nYear-over-year change: -2432987 (≈ 2.43 billion U.S. Dollars; -3.991%) [S4]") in pack
    _handoff_dir, carrier = _handoff(env, "q2_datacenter")
    pack = _agent(monkeypatch, "q2_datacenter", carrier)._data_pack
    assert "(usgov:eia/electricity_sales/US.COM) | 150578.728 (≈ 150.58 billion kilowatt-hours) / 2026-07 |" in pack
    # Under a billion, or already in billions, the stored value stands alone.
    assert "(usgov:eia/net_generation/NG) | 205294.0875 / 2026-07 |" in pack
    assert "(usgov:bea/value_added_by_industry/514) | 694.7 / 2026-Q2 |" in pack
    api = data_api()
    zh = ra._official_value_display(api, 58522249, "Thousands of U.S. Dollars", "zh", rescale=True)
    assert zh == "58522249 (≈585.22亿美元)"
    # Published displays (the indicator table, the API the frontend mirrors) keep the data layer's rule.
    assert ra._official_value_display(api, 58522249, "Thousands of U.S. Dollars", "en") == "58522249"
    assert ra.official_indicator_rows(carrier)[0]["latest"]["display"] == "150578.728"


# ------------------------------------------------------------- the outside view in every judging prompt


def test_critique_premortem_and_fallback_packs_carry_the_outside_view(env, monkeypatch):
    """Their base-rate-neglect checks see the empirical base rate, to the calendar horizon."""
    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    _calendar_horizon(env, "q1_cpi_fed")
    agent = _agent(monkeypatch, "q1_cpi_fed", carrier)
    data_pack = agent._official_pack_kwargs()["data_pack"]
    outside = fe.official_outside_view_block(carrier, "2027-12-31", "English")
    assert data_pack == agent._data_pack + "\n\n" + outside
    assert "; 16-month change to the horizon 2027-12 (n=101): p10" in outside  # from 2026-08

    model = FakeLLMClient(json_responses=[{"scenarios": []}, {"risks": []}])
    forecast = {"headline": "h", "scenarios": [{"name": "Base", "probability": 1.0, "resolution_criteria": "r"}]}
    fe.self_critique_forecast(deepcopy(forecast), model, language="English", data_pack=data_pack)
    fe.premortem_forecast(deepcopy(forecast), model, language="English", data_pack=data_pack)
    assert len(model.calls) == 2
    for index in range(2):
        prompt = _prompt(model, index)
        assert "(fred:UNRATE) | 4.2% / 2026-09 |" in prompt  # the pack's last row, uncut
        assert outside.split("\n")[-2] in prompt and outside.split("\n")[-1] in prompt  # the view, uncut


def test_calibration_and_indicator_sections_get_the_outside_view(env, monkeypatch):
    """With how to quote it: a computed quantile is this report's calculation, never a [S#]
    claim (the citation audit checks every marker against stored values)."""
    _handoff_dir, carrier = _handoff(env, "q6_china_gdp_zh")
    agent = _agent(monkeypatch, "q6_china_gdp_zh", carrier)
    outside = agent._official_outside_view()
    assert outside.startswith(OUTSIDE_VIEW["Chinese"])
    note = ReportAgent._OFFICIAL_SECTION_BASE_RATE_NOTE["zh"]
    assert "据本报告根据已存储历史计算" in note and "不加 [S#] 来源标记" in note
    for title in ("Base rates and calibration", "Key official indicators and what they imply",
                  "基率与概率校准", "关键统计与指标"):
        assert agent._section_official_blocks(title) == [outside + "\n" + note], title
        assert agent._prepend_research_background("PROMPT", title).endswith(
            outside + "\n" + note + "\n\nPROMPT")
    for title in ("Actors and coalitions", "Data-center demand and grid constraints", "政策博弈与主要行为者",
                  "数据中心用电需求", ""):
        assert agent._section_official_blocks(title) == [], title
        assert OUTSIDE_VIEW["Chinese"] not in agent._prepend_research_background("PROMPT", title)
    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    english = _agent(monkeypatch, "q1_cpi_fed", carrier)
    assert english._section_official_blocks("Base rates and calibration") == [
        english._official_outside_view() + "\n" + ReportAgent._OFFICIAL_SECTION_BASE_RATE_NOTE["en"]]
    assert "this report's own calculation" in ReportAgent._OFFICIAL_SECTION_BASE_RATE_NOTE["en"]


def test_outline_rule_asks_for_an_indicator_section_only_for_series_that_measure_the_question():
    rule = ra.OFFICIAL_DATA_PLAN_RULE
    assert "若其中有序列直接度量核心问题" in rule
    assert "发布方预测与本报告判断的差异" in rule
    assert "只作背景的序列" in rule and "不要为其单设章节" in rule


def test_spine_facts_keep_the_whole_pack(env, monkeypatch):
    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    agent = _agent(monkeypatch, "q1_cpi_fed", carrier)
    facts = agent._build_data_pack(budget=agent._spine_facts_budget())
    assert facts == agent._data_pack and len(facts) > 3500
    model = FakeLLMClient(json_responses=[{"scenarios": []}])
    fe.derive_forecast_spine(model, central_question=QUESTIONS["q1_cpi_fed"]["question"], horizon="2027-12-31",
                             quantitative_facts=facts, language="English", official_data=carrier)
    prompt = _prompt(model)
    assert facts in prompt
    assert "(fred:UNRATE): latest 4.2% (2026-09)" in prompt  # the outside view's last series


# ------------------------------------------------------------- binary extraction


def _binary_prompt(carrier, pack, horizon, language="English"):
    model = FakeLLMClient(json_responses=[{"binary_forecasts": []}] * 3)
    fe.extract_binary_forecasts("# Report\n\nBody.", model, min_count=1, language=language, horizon_date=horizon,
                                data_pack=pack, official_data=carrier)
    return _prompt(model)


@pytest.mark.parametrize("key", ["q1_cpi_fed", "q6_china_gdp_zh"])
def test_binary_prompt_carries_the_whole_pack_under_one_header(env, monkeypatch, key):
    _handoff_dir, carrier = _handoff(env, key)
    pack = _agent(monkeypatch, key, carrier)._data_pack
    prompt = _binary_prompt(carrier, pack, QUESTIONS[key]["horizon_date"], QUESTIONS[key]["language"])
    assert prompt.count("[Official data snapshot") == 1
    assert "\n\n" + pack + "\nWhenever a binary's metric is one of the listed series, add data_anchor" in prompt
    assert "optionally" not in prompt
    assert ("('on 31 December 2026' or 'at the end of 2026' -> 2026-12; 'by the end of 2026' is a deadline, "
            "not a period)") in prompt
    assert "an exact-value statement ('is 4.25%') cannot be anchored" in prompt
    assert ("In the statement, name the metric as the snapshot lists it (its title, or a short form keeping the "
            "title's distinctive words, such as 'the US unemployment rate'); when your wording differs from the "
            "title, put the canonical ID in parentheses right after it (such as 'the US jobless rate "
            "(fred:UNRATE)'), or the anchor cannot be verified and is dropped.") in prompt
    assert OUTSIDE_VIEW[QUESTIONS[key]["language"]] in prompt


def test_outside_view_states_level_changes_in_percent_and_keeps_every_series(env):
    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    block = fe.official_outside_view_block(carrier, "2027-12-31", "English")
    lines = block.split("\n")
    assert "omitted" not in block and len(block) <= 3600
    for row in carrier["series"]:
        assert f"({row['series']}): latest" in block, row["series"]
    cpi = next(line for line in lines if "(fred:CPIAUCSL): latest" in line)
    assert cpi.endswith("16-month change to the horizon 2027-12 (n=101): p10 +5.684, median +11.594, p90 +26.156; "
                        "as % change: p10 +2.278%, median +3.767%, p90 +9.592%.")
    unrate = next(line for line in lines if "(fred:UNRATE): latest" in line)
    assert "as % change" not in unrate and unrate.endswith("p90 +2.58 pp.")

    _handoff_dir, carrier = _handoff(env, "q2_datacenter")
    block = fe.official_outside_view_block(carrier, "2030-12-31", "English")
    sales = next(line for line in block.split("\n") if "(usgov:eia/electricity_sales/US.COM): latest" in line)
    # July 2026 to December 2030 of NSA sales: the seasonal profile keeps the summer-to-winter fall
    # (the season-blind pool read median +5.636%, p90 +32.981%).
    assert sales.endswith("53-month change to the horizon 2030-12 (n=64; seasonal profile): p10 -23623.212, "
                          "median -17137.7014, p90 -4928.7108; as % change: p10 -19.784%, median -13.594%, "
                          "p90 -2.224%.")
    zh = fe.official_outside_view_block(carrier, "2030-12-31", "Chinese")
    assert "（n=64；同月季节均值）" in zh and "；按百分比变化：p10 -19.784%，中位数 -13.594%，p90 -2.224%。" in zh


def test_outside_view_names_the_window_each_quantile_describes(env):
    """'16-period change quantiles' left the model to guess that the 16 periods were months from
    the latest observation to the horizon; a standard 12-month window is now said to be one."""
    def line(block, series):
        return next(text for text in block.split("\n") if f"({series}): latest" in text or f"（{series}）" in text)

    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    horizon = fe.official_outside_view_block(carrier, "2027-12-31", "English")
    assert line(horizon, "bis:WS_LONG_CPI/M.US.771").endswith(
        "latest 3.397% (2026-08); 117 historical months 2016-11 to 2026-08, latest at percentile 73 of that "
        "history; 16-month change to the horizon 2027-12 (n=101): p10 -3.432 pp, median -0.312 pp, p90 +5.272 pp.")
    standard = fe.official_outside_view_block(carrier, None, "English")
    assert line(standard, "bis:WS_LONG_CPI/M.US.771").endswith(
        "; 12-month change (a standard window, not the horizon; n=105): p10 -3.014 pp, median -0.323 pp, "
        "p90 +3.988 pp.")
    zh = fe.official_outside_view_block(carrier, "2027-12-31", "Chinese")
    assert line(zh, "bis:WS_LONG_CPI/M.US.771").endswith(
        "；至预测期末 2027-12 的 16 个月变化经验分位（n=101）：p10 -3.432 pp，中位数 -0.312 pp，p90 +5.272 pp。")
    zh_standard = fe.official_outside_view_block(carrier, None, "Chinese")
    assert "；12 个月变化经验分位（标准窗口，非预测期末；n=105）：p10 -3.014 pp" in line(
        zh_standard, "bis:WS_LONG_CPI/M.US.771")
    # 2030-Q4 lies further ahead than 38 stored quarters can sample 30 times.
    _handoff_dir, carrier = _handoff(env, "q2_datacenter")
    quarterly = fe.official_outside_view_block(carrier, "2030-12-31", "English")
    assert "; 4-quarter change (a standard window, not the horizon; n=34): p10 +21.02," in line(
        quarterly, "usgov:bea/value_added_by_industry/514")
    assert "omitted" not in quarterly  # all eight series still fit the 3600-character view
    assert "-period change" not in horizon + standard + quarterly and " 期变化" not in zh + zh_standard


DFEDTARU_GE = {"series": "fred:DFEDTARU", "comparator": ">=", "threshold": 4.5, "observation": "2026-12",
               "transform": "", "units": "Percent"}
CBPOL_US_LE = {"series": "bis:WS_CBPOL/M.US", "comparator": "<=", "threshold": 3.5, "observation": "2027-12",
               "transform": "", "units": "Per cent per year"}
CBPOL_XM_LE = {"series": "bis:WS_CBPOL/M.XM", "comparator": "<=", "threshold": 2.25, "observation": "2026-12",
               "transform": "", "units": "Per cent per year"}
ECBDFR_LE = {"series": "fred:ECBDFR", "comparator": "<=", "threshold": 2.25, "observation": "2026-12",
             "transform": "", "units": "Percent"}
DFEDTARU_CRITERIA = "Resolves YES if fred:DFEDTARU >= 4.5% in 2026-12 (source: FRED)."
MONTH_END_CASES = [
    # The real run's (pipe_261de6107490) phrasing, now anchorable on the end-of-month series.
    ("q1_cpi_fed", "The upper bound of the federal funds target range is at least 4.50% on 31 December 2026.",
     DFEDTARU_CRITERIA, DFEDTARU_GE, True),
    ("q1_cpi_fed", "The upper limit of the federal funds target range is at least 4.5% on December 31, 2026.",
     DFEDTARU_CRITERIA, DFEDTARU_GE, True),
    ("q1_cpi_fed", "The upper limit of the federal funds target range is at least 4.5% at the end of December 2026.",
     "Resolves YES if fred:DFEDTARU >= 4.5% on 2026-12-31 (source: FRED).", DFEDTARU_GE, True),
    ("q1_cpi_fed", "The upper limit of the federal funds target range is at least 4.5% at year-end 2026.",
     DFEDTARU_CRITERIA, DFEDTARU_GE, True),
    ("q1_cpi_fed", "2026年底联邦基金目标利率区间上限不低于4.5%。",
     "若 fred:DFEDTARU >= 4.5% 于 2026-12（来源：FRED），判定为是。", DFEDTARU_GE, True),
    ("q1_cpi_fed", "The US central bank policy rate is at most 3.5% at the end of 2027.",
     "Resolves YES if bis:WS_CBPOL/M.US <= 3.5% in 2027-12 (source: BIS).", CBPOL_US_LE, True),
    ("q4_ecb_dfr", "The ECB deposit facility rate is at most 2.25% at the end of 2026.",
     "Resolves YES if bis:WS_CBPOL/M.XM <= 2.25% in 2026-12 (source: BIS).", CBPOL_XM_LE, True),
    ("q4_ecb_dfr", "The euro-area policy rate is at most 2.25% on 31 December 2026.",
     "Resolves YES if bis:WS_CBPOL/M.XM <= 2.25 Per cent per year in 2026-12 (source: BIS).", CBPOL_XM_LE, True),
    # A deadline, another day, or a monthly mean of daily data stays unanchored.
    ("q1_cpi_fed", "The upper limit of the federal funds target range is at least 4.5% by the end of 2026.",
     DFEDTARU_CRITERIA, DFEDTARU_GE, False),
    ("q1_cpi_fed", "The upper limit of the federal funds target range is at least 4.5% on 15 December 2026.",
     DFEDTARU_CRITERIA, DFEDTARU_GE, False),
    ("q1_cpi_fed", "The upper limit of the federal funds target range is at least 4.5% on 30 November 2026.",
     DFEDTARU_CRITERIA, DFEDTARU_GE, False),
    ("q4_ecb_dfr", "The ECB deposit facility rate is at most 2.25% at the end of 2026.",
     "Resolves YES if fred:ECBDFR <= 2.25% in 2026-12 (source: FRED).", ECBDFR_LE, False),
    ("q4_ecb_dfr", "The ECB deposit facility rate is at most 2.25% on 31 December 2026.",
     "Resolves YES if fred:ECBDFR <= 2.25% in 2026-12 (source: FRED).", ECBDFR_LE, False),
]


@pytest.mark.parametrize("key, statement, criteria, anchor, admitted", MONTH_END_CASES)
def test_month_end_wording_anchors_only_end_of_month_series(env, key, statement, criteria, anchor, admitted):
    _handoff_dir, carrier = _handoff(env, key)
    out = fe._normalize_binaries([{"statement": statement, "probability": 0.3, "resolution_criteria": criteria,
                                   "data_anchor": dict(anchor)}], official_data=carrier)
    assert ("data_anchor" in out[0]) is admitted, statement
    if admitted:
        assert out[0]["data_anchor"]["observation"] == anchor["observation"]


def _anchor(series, comparator, threshold, observation, units):
    return {"series": series, "comparator": comparator, "threshold": threshold, "observation": observation,
            "transform": "", "units": units}


US_COM_GE = _anchor("usgov:eia/electricity_sales/US.COM", ">=", 160000, "2030-07", "Million kilowatt-hours")
US_COM_CRITERIA = ("Resolves YES if usgov:eia/electricity_sales/US.COM >= 160000 Million kilowatt-hours in 2030-07 "
                   "(source: EIA).")
SEMIS_GT = _anchor("fred:AIES334413RCTUS", ">", 70000000, "2027", "Thousands of U.S. Dollars")
SEMIS_CRITERIA = "Resolves YES if fred:AIES334413RCTUS > 70000000 Thousands of U.S. Dollars in 2027 (source: FRED)."
WEO_US_LT = _anchor("wb:IMF_WEO_PCPIPCH/USA", "<", 2.5, "2027", "Percent change")
WEO_US_STATEMENT = "The IMF's 2027 US CPI inflation figure is below 2.5% (IMF WEO)."
WDI_CHN_LT = _anchor("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN", "<", 4, "2027", "Percent change per annum")
WDI_CHN_CRITERIA = "若 wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN < 4% 于 2027（来源：世界银行），判定为是。"
ECBDFR_LT = _anchor("fred:ECBDFR", "<", 2.5, "2026-12", "Percent")
ECBDFR_CRITERIA = "Resolves YES if fred:ECBDFR < 2.5% in 2026-12 (source: FRED)."
CORE_BINARY_CASES = [
    # EIA units carry a scale word without 'of' ('Million kilowatt-hours'): a written scale converts,
    # a bare amount in kilowatt-hours is a millionth of the threshold.
    ("q2_datacenter", "US commercial-sector retail electricity sales are at least 160,000 million kilowatt-hours "
     "in July 2030.", US_COM_CRITERIA, US_COM_GE, True),
    ("q2_datacenter", "US commercial electricity sales are at least 160 billion kilowatt-hours in July 2030.",
     US_COM_CRITERIA, US_COM_GE, True),
    ("q2_datacenter", "US commercial electricity sales are at least 160,000 kilowatt-hours in July 2030.",
     US_COM_CRITERIA, US_COM_GE, False),
    ("q2_datacenter", "US natural gas generation is above 220,000 thousand megawatt-hours in July 2030.",
     "Resolves YES if usgov:eia/net_generation/NG > 220000 Thousand megawatt-hours in 2030-07 (source: EIA).",
     _anchor("usgov:eia/net_generation/NG", ">", 220000, "2030-07", "Thousand megawatt-hours"), True),
    # The prompt's fallback: a plain name followed by the canonical ID.
    ("q2_datacenter", "The US average retail price of electricity (usgov:eia/electricity_price/US.ALL) is above "
     "17 cents per kilowatt-hour in July 2030.",
     "Resolves YES if usgov:eia/electricity_price/US.ALL > 17 Cents per kilowatt-hour in 2030-07 (source: EIA).",
     _anchor("usgov:eia/electricity_price/US.ALL", ">", 17, "2030-07", "Cents per kilowatt-hour"), True),
    ("q5_semis", "US semiconductor production (fred:IPG3344S) is at least 220 in December 2030.",
     "Resolves YES if fred:IPG3344S >= 220 Index 2017=100 in 2030-12 (source: FRED).",
     _anchor("fred:IPG3344S", ">=", 220, "2030-12", "Index 2017=100"), True),
    # An annual year may end the sentence; a dollar amount without its scale word is a thousandth.
    ("q5_semis", "US semiconductor and related device manufacturing shipments exceed $70 billion in 2027.",
     SEMIS_CRITERIA, SEMIS_GT, True),
    ("q5_semis", "US semiconductor and related device manufacturing shipments exceed $70,000,000 in 2027.",
     SEMIS_CRITERIA, SEMIS_GT, False),
    # A provider whose name carries digits is not a second number; a release date still is.
    ("q1_cpi_fed", WEO_US_STATEMENT,
     "Resolves YES if wb:IMF_WEO_PCPIPCH/USA < 2.5% in 2027 (source: IMF WEO via World Bank Data360).",
     WEO_US_LT, True),
    ("q1_cpi_fed", WEO_US_STATEMENT,
     "Resolves YES if wb:IMF_WEO_PCPIPCH/USA < 2.5% in 2027 (source: World Bank Data360, April 2028 release).",
     WEO_US_LT, False),
    # Chinese prose: 增速 names a 增长率 series; nominal growth or another economy does not.
    ("q6_china_gdp_zh", "2027年中国GDP增速低于4%。", WDI_CHN_CRITERIA, WDI_CHN_LT, True),
    ("q6_china_gdp_zh", "2027年中国GDP年增速低于4%。", WDI_CHN_CRITERIA, WDI_CHN_LT, True),
    ("q6_china_gdp_zh", "2027年中国名义GDP增速低于4%。", WDI_CHN_CRITERIA, WDI_CHN_LT, False),
    ("q6_china_gdp_zh", "2027年世界GDP增速低于4%。", WDI_CHN_CRITERIA, WDI_CHN_LT, False),
    # A FRED series stored without a geography takes its catalog / title geography (euro area).
    ("q4_ecb_dfr", "The ECB deposit facility rate averages below 2.5% in December 2026.", ECBDFR_CRITERIA,
     ECBDFR_LT, True),
    ("q4_ecb_dfr", "The Japanese deposit facility rate averages below 2.5% in December 2026.", ECBDFR_CRITERIA,
     ECBDFR_LT, False),
]


@pytest.mark.parametrize("key, statement, criteria, anchor, admitted", CORE_BINARY_CASES)
def test_core_binaries_of_the_audit_questions_keep_their_anchor(env, key, statement, criteria, anchor, admitted):
    """Natural binaries on each question's headline series: before, every EIA anchor ('Million
    kilowatt-hours'), every annual statement ending '… in 2027.', 增速 phrasings, 'World Bank
    Data360' sources and the euro-area ECBDFR series lost their anchor."""
    _handoff_dir, carrier = _handoff(env, key)
    out = fe._normalize_binaries([{"statement": statement, "probability": 0.3, "resolution_criteria": criteria,
                                   "data_anchor": dict(anchor)}], official_data=carrier,
                                 language=QUESTIONS[key]["language"])
    assert ("data_anchor" in out[0]) is admitted, statement
    if admitted:
        assert out[0]["data_anchor"]["series"] == anchor["series"]
        assert out[0]["data_anchor"]["threshold"] == anchor["threshold"]


BIS_US_LT = _anchor("bis:WS_LONG_CPI/M.US.771", "<", 2.5, "2027-12", "Per cent, year-on-year change")
BIS_US_CRITERIA = "Resolves YES if bis:WS_LONG_CPI/M.US.771 < 2.5% in 2027-12 (source: BIS)."
WEO_US_CRITERIA = "Resolves YES if wb:IMF_WEO_PCPIPCH/USA < 2.5% in 2027 (source: IMF WEO)."
IP_SEMIS_GE = _anchor("fred:IPG3344S", ">=", 220, "2030-12", "Index 2017=100")
IP_SEMIS_CRITERIA = "Resolves YES if fred:IPG3344S >= 220 Index 2017=100 in 2030-12 (source: FRED)."
UNRATE_LT = _anchor("fred:UNRATE", "<", 2.5, "2027-12", "Percent")
UNRATE_CRITERIA = "Resolves YES if fred:UNRATE < 2.5% in 2027-12 (source: FRED)."
EIA_COM_GE = _anchor("usgov:eia/electricity_sales/US.COM", ">=", 140000, "2026-12", "Million kilowatt-hours")
EIA_COM_CRITERIA = ("Resolves YES if usgov:eia/electricity_sales/US.COM >= 140000 Million kilowatt-hours in 2026-12 "
                    "(source: EIA).")
BREAKEVEN_LT = _anchor("fred:T10YIE", "<", 2.5, "2027-12", "Percent")
BREAKEVEN_CRITERIA = "Resolves YES if fred:T10YIE < 2.5% in 2027-12 (source: FRED)."
PPI_SEMIS_GT = _anchor("fred:PCU33443344", ">", 60, "2027-12", "Index Dec 1984=100")
PPI_SEMIS_CRITERIA = "Resolves YES if fred:PCU33443344 > 60 Index Dec 1984=100 in 2027-12 (source: FRED)."
RECALL_CASES = [
    # A multi-word catalog keyword in natural number and word order ('consumer prices' ->
    # 'consumer price inflation', 'semiconductor production' -> 'industrial production of
    # semiconductors'), joined only by the series' own title words.
    ("q1_cpi_fed", "US year-on-year consumer price inflation is below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, True),
    ("q1_cpi_fed", "US annual consumer price inflation is below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, True),
    ("q5_semis", "US industrial production of semiconductors is at least 220 in December 2030.",
     IP_SEMIS_CRITERIA, IP_SEMIS_GE, True),
    ("q5_semis", "US semiconductor industrial production is at least 220 in December 2030.",
     IP_SEMIS_CRITERIA, IP_SEMIS_GE, True),
    # The catalog's 'cpi' names consumer prices on the IMF WEO entry, which lists no 'consumer prices'.
    ("q1_cpi_fed", "US consumer price inflation is below 2.5% in 2027.", WEO_US_CRITERIA, WEO_US_LT, True),
    # Overlapping names join into one ('10-year breakeven inflation' + 'inflation expectations').
    ("q1_cpi_fed", "US 10-year breakeven inflation expectations are below 2.5% in December 2027.",
     BREAKEVEN_CRITERIA, BREAKEVEN_LT, True),
    # Negation, compounds, deadlines, other periods, places, metrics and siblings stay unanchored.
    ("q1_cpi_fed", "US year-on-year consumer price inflation is not below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US year-on-year consumer price inflation and unemployment are below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US year-on-year consumer price inflation is below 2.5% by December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US year-on-year consumer price inflation is below 2.5% in November 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "Euro-area consumer price inflation is below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US core consumer price inflation is below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US producer price inflation is below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US consumer price inflation is below 2.5% in 2028.", WEO_US_CRITERIA, WEO_US_LT, False),
    ("q5_semis", "US semiconductor and auto industrial production is at least 220 in December 2030.",
     IP_SEMIS_CRITERIA, IP_SEMIS_GE, False),
    ("q5_semis", "US industrial production of cars is at least 220 in December 2030.",
     IP_SEMIS_CRITERIA, IP_SEMIS_GE, False),
    ("q5_semis", "Taiwan semiconductor industrial production is at least 220 in December 2030.",
     IP_SEMIS_CRITERIA, IP_SEMIS_GE, False),
    # Inflation expectations are a sibling of realized inflation (this anchored before).
    ("q1_cpi_fed", "US CPI inflation expectations are below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US consumer price inflation expectations are below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "美国CPI通胀预期在2027年12月低于2.5%。", BIS_US_CRITERIA, BIS_US_LT, False),
    # A component or population subgroup of the headline series is a different series (these
    # anchored before, so a services-inflation or Black-unemployment call settled on the headline).
    ("q1_cpi_fed", "US consumer price inflation of services is below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US services consumer price inflation is below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US consumer prices of food rise less than 2.5% year on year in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US consumer price inflation for urban wage earners is below 2.5% in December 2027.",
     BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "美国CPI同比在2027年12月低于2.5%。", BIS_US_CRITERIA, BIS_US_LT, True),
    ("q1_cpi_fed", "美国服务CPI同比在2027年12月低于2.5%。", BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "美国女性失业率在2027年12月低于2.5%。", UNRATE_CRITERIA, UNRATE_LT, False),
    ("q1_cpi_fed", "The US unemployment rate for Black workers is below 2.5% in December 2027.",
     UNRATE_CRITERIA, UNRATE_LT, False),
    ("q1_cpi_fed", "The US unemployment rate of college graduates is below 2.5% in December 2027.",
     UNRATE_CRITERIA, UNRATE_LT, False),
    ("q1_cpi_fed", "The US unemployment rate is below 2.5% in December 2027.", UNRATE_CRITERIA, UNRATE_LT, True),
    # ... while a series whose own names carry the word keeps it (EIA's commercial sector).
    ("q2_datacenter", "US commercial-sector retail electricity sales are at least 140,000 million kilowatt-hours "
     "in December 2026.", EIA_COM_CRITERIA, EIA_COM_GE, True),
    ("q2_datacenter", "US residential retail electricity sales are at least 140,000 million kilowatt-hours "
     "in December 2026.", EIA_COM_CRITERIA, EIA_COM_GE, False),
    # The ECB's main refinancing and marginal lending rates are siblings of its deposit facility
    # rate (which BIS reports as the euro-area policy rate since 18 Sep 2024): naming the
    # institution ('European Central Bank', a catalog name of both series) does not make either
    # the anchored series.
    ("q4_ecb_dfr", "The European Central Bank deposit facility rate is below 2.5% in December 2026.",
     ECBDFR_CRITERIA, ECBDFR_LT, True),
    ("q4_ecb_dfr", "The European Central Bank main refinancing rate is below 2.5% in December 2026.",
     ECBDFR_CRITERIA, ECBDFR_LT, False),
    ("q4_ecb_dfr", "The European Central Bank marginal lending facility rate is below 2.5% in December 2026.",
     ECBDFR_CRITERIA, ECBDFR_LT, False),
    ("q4_ecb_dfr", "The European Central Bank main refinancing rate is at most 2.25% at the end of 2026.",
     "Resolves YES if bis:WS_CBPOL/M.XM <= 2.25% in 2026-12 (source: BIS).", CBPOL_XM_LE, False),
    ("q4_ecb_dfr", "欧洲央行主要再融资利率在2026年底不高于2.25%。",
     "Resolves YES if bis:WS_CBPOL/M.XM <= 2.25% in 2026-12 (source: BIS).", CBPOL_XM_LE, False),
    ("q4_ecb_dfr", "欧洲央行政策利率在2026年底不高于2.25%。",
     "Resolves YES if bis:WS_CBPOL/M.XM <= 2.25% in 2026-12 (source: BIS).", CBPOL_XM_LE, True),
    # Likewise the Fed's discount (primary credit) rate and interest on reserve balances are
    # siblings of the US policy rate BIS reports ('Federal Reserve' is a catalog name of it).
    ("q1_cpi_fed", "The Federal Reserve policy rate is at most 3.5% in December 2027.",
     "Resolves YES if bis:WS_CBPOL/M.US <= 3.5% in 2027-12 (source: BIS).", CBPOL_US_LE, True),
    ("q1_cpi_fed", "The Federal Reserve discount rate is at most 3.5% in December 2027.",
     "Resolves YES if bis:WS_CBPOL/M.US <= 3.5% in 2027-12 (source: BIS).", CBPOL_US_LE, False),
    ("q1_cpi_fed", "The Federal Reserve interest rate on reserve balances is at most 3.5% in December 2027.",
     "Resolves YES if bis:WS_CBPOL/M.US <= 3.5% in 2027-12 (source: BIS).", CBPOL_US_LE, False),
    ("q1_cpi_fed", "The Federal Reserve primary credit rate is at most 3.5% in December 2027.",
     "Resolves YES if bis:WS_CBPOL/M.US <= 3.5% in 2027-12 (source: BIS).", CBPOL_US_LE, False),
    ("q1_cpi_fed", "美联储贴现率在2027年12月不高于3.5%。",
     "Resolves YES if bis:WS_CBPOL/M.US <= 3.5% in 2027-12 (source: BIS).", CBPOL_US_LE, False),
    # 'Headline inflation' (整体通胀) names the all-items consumer price series, but not another
    # price measure's headline rate (PCE, producer prices) nor inflation expectations (通胀预期).
    ("q1_cpi_fed", "US headline inflation is below 2.5% in December 2027.", BIS_US_CRITERIA, BIS_US_LT, True),
    ("q1_cpi_fed", "美国整体通胀在2027年12月低于2.5%。", BIS_US_CRITERIA, BIS_US_LT, True),
    ("q1_cpi_fed", "US PCE headline inflation is below 2.5% in December 2027.", BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US headline inflation, as measured by the personal consumption expenditures price index, is below "
     "2.5% in December 2027.", BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "US producer price headline inflation is below 2.5% in December 2027.", BIS_US_CRITERIA, BIS_US_LT,
     False),
    ("q1_cpi_fed", "美国PCE整体通胀在2027年12月低于2.5%。", BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "美国PPI整体通胀在2027年12月低于2.5%。", BIS_US_CRITERIA, BIS_US_LT, False),
    ("q1_cpi_fed", "美国整体通胀预期在2027年12月低于2.5%。", BIS_US_CRITERIA, BIS_US_LT, False),
    # ... while a producer price series keeps its own acronym and full name.
    ("q5_semis", "The US semiconductor PPI is above 60 in December 2027.", PPI_SEMIS_CRITERIA, PPI_SEMIS_GT, True),
    ("q5_semis", "The US semiconductor producer price index is above 60 in December 2027.", PPI_SEMIS_CRITERIA,
     PPI_SEMIS_GT, True),
]


@pytest.mark.parametrize("key, statement, criteria, anchor, admitted", RECALL_CASES)
def test_natural_metric_wordings_keep_their_anchor_and_counterexamples_do_not(env, key, statement, criteria,
                                                                              anchor, admitted):
    """Recall: wordings that use neither the title words nor an exact catalog name lost their anchor
    ('year-on-year consumer price inflation', 'industrial production of semiconductors')."""
    _handoff_dir, carrier = _handoff(env, key)
    out = fe._normalize_binaries([{"statement": statement, "probability": 0.3, "resolution_criteria": criteria,
                                   "data_anchor": dict(anchor)}], official_data=carrier,
                                 language=QUESTIONS[key]["language"])
    assert ("data_anchor" in out[0]) is admitted, statement


def test_a_year_ending_the_sentence_is_its_period():
    text = "Shipments exceed $70 billion in 2027."
    assert fe._anchor_periods(text) == [(text.index("2027"), text.index("2027") + 4, ("A", "2027"), False)]
    assert fe._anchor_periods("Output reached 2027.5 units") == []


@pytest.mark.parametrize("key, series, claim, supported", [
    ("q2_datacenter", "usgov:eia/electricity_sales/US.COM",
     "US commercial electricity sales were 150,578.728 million kilowatt-hours in July 2026.", True),
    ("q2_datacenter", "usgov:eia/electricity_sales/US.COM",
     "US commercial electricity sales were 150.58 billion kilowatt-hours in July 2026.", True),
    ("q2_datacenter", "usgov:eia/electricity_sales/US.COM",
     "US commercial electricity sales were 160,000 million kilowatt-hours in July 2026.", False),
    ("q5_semis", "fred:AIES334413RCTUS", "US semiconductor shipments were $58.52 billion in 2024.", True),
    ("q5_semis", "fred:AIES334413RCTUS", "US semiconductor shipments were $61 billion in 2024.", False),
    ("q6_china_gdp_zh", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN", "China's GDP grew 4.96% in 2025.", True),
    ("q6_china_gdp_zh", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN", "China's GDP grew 5.2% in 2025.", False),
])
def test_report_claims_in_scale_word_units_and_ending_with_a_year_are_checked(env, key, series, claim, supported):
    """RPT-1 on real rows: a true '150,578.728 million kilowatt-hours' claim was judged contradicted
    (its [S#] stripped) and a claim ending '… in 2024.' could not be checked at all."""
    _handoff_dir, carrier = _handoff(env, key)
    row = next(row for row in fe.official_series_rows(carrier) if row["series"] == series)
    prepared = ra.prepare_official_row(row, fe.official_observation_kinds(row))
    assert ra.official_claim_support(claim, prepared) is supported


def test_end_of_period_detection_prefers_the_data_layer_aggregation():
    eop_title = {"frequency": "M", "title": "Central bank policy rates - Euro area - Monthly - End of period"}
    assert fe._anchor_end_of_month(eop_title)
    assert fe._anchor_end_of_month({"frequency": "M", "title": "x", "provenance": {"aggregation_method": "eop"}})
    # Aggregated by the data layer as a monthly mean: the title cannot override it.
    assert not fe._anchor_end_of_month({**eop_title, "provenance": {"aggregation_method": "avg"}})
    assert not fe._anchor_end_of_month({**eop_title, "frequency": "Q"})
    assert not fe._anchor_end_of_month({"frequency": "M", "title": "Consumer prices: Euro area"})


# ------------------------------------------------------------- the simulation world brief


def _world_brief(key, carrier, window, adaptive, monkeypatch):
    monkeypatch.setattr(Config, "ADAPTIVE_CONTEXT", adaptive, raising=False)
    question = QUESTIONS[key]
    filler = ("Research found mixed evidence across official statistics, industry releases and policy "
              "statements; the main tension is between momentum in recent data and structural constraints. ")
    actors = {"as_of_date": "2026-10-13", "situation_brief": {
        "current_situation": filler * 3, "context": filler * 3, "dynamics": filler * 2,
        "fault_lines": [f"Fault line {i}: competing readings of the latest data" for i in range(1, 6)],
        "catalysts": [f"Catalyst {i}: scheduled release or policy decision" for i in range(1, 7)]}}
    topics = [f"Hot topic {i} about {question['question'][:40]}" for i in range(1, 9)]
    gen = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    gen._output_language = question["language"]
    gen.provider = "minimax"
    return gen._build_world_brief(question["question"], actors, topics, MARKETS, None,
                                  official_data=carrier, official_window=window), gen._world_brief_max_chars()


@pytest.mark.parametrize("adaptive", [True, False])
@pytest.mark.parametrize("key", sorted(QUESTIONS))
def test_world_brief_shares_its_budget_with_the_official_snapshot(env, monkeypatch, key, adaptive):
    """Every simulated actor now sees the official statistics: the snapshot gets a fair
    share of the brief instead of what question, situation, topics and markets left (nothing)."""
    handoff, carrier = _handoff(env, key)
    brief, max_chars = _world_brief(key, carrier, research_run_window(handoff), adaptive, monkeypatch)
    assert max_chars == (3000 if adaptive else 1400)
    assert len(brief) <= max_chars
    assert brief.count("BEGIN UNTRUSTED RESEARCH DATA — official public historical statistics") == 1
    header = SimulationConfigGenerator.OFFICIAL_SNAPSHOT_HEADER[QUESTIONS[key]["language"] == "English"]
    assert header + "\nBEGIN UNTRUSTED RESEARCH DATA" in brief  # framing outside the untrusted block
    assert brief.rstrip().endswith("END UNTRUSTED RESEARCH DATA — official public historical statistics")
    assert QUESTIONS[key]["question"] in brief
    # The first row is the first series the question names (else the carrier's first), named in
    # the brief's language (the snapshot table may set full-width parentheses as ASCII).
    first = SimulationConfigGenerator._official_data_for_question(carrier, QUESTIONS[key]["question"])["series"][0]
    label = data_api().series_label(first, "zh" if QUESTIONS[key]["language"] == "Chinese" else "en")
    parens = str.maketrans("（）", "()")
    assert label.translate(parens) in brief.split("BEGIN UNTRUSTED")[1].translate(parens)
    # The situation brief and topics keep their share, cut at lines and then words.
    situation, topics = (("## 局势简报", "## 热点话题") if QUESTIONS[key]["language"] == "Chinese"
                         else ("## Situation brief", "## Hot topics"))
    assert situation in brief and topics in brief
    assert "…" in brief.split("BEGIN UNTRUSTED")[0]


CPI_SERIES = {"fred:CPIAUCSL", "bis:WS_LONG_CPI/M.US.771", "wb:IMF_WEO_PCPIPCH/USA"}
POLICY_RATE_SERIES = {"fred:DFEDTARU", "fred:FEDFUNDS", "bis:WS_CBPOL/M.US"}
POWER_SALES_SERIES = {"usgov:eia/electricity_sales/US.COM", "usgov:eia/electricity_sales/VA.COM",
                      "usgov:eia/electricity_sales/TX.COM", "usgov:eia/electricity_sales/US.ALL"}


@pytest.mark.parametrize("key, clauses", [
    ("q1_cpi_fed", [CPI_SERIES, POLICY_RATE_SERIES]),
    ("q2_datacenter", [POWER_SALES_SERIES, {"usgov:eia/electricity_price/US.ALL"}]),
])
def test_world_brief_rows_cover_every_clause_the_question_names(env, monkeypatch, key, clauses):
    """The brief has room for two or three rows; they went to the first clause's series
    (two CPI rows, no policy rate; two sales rows, no power price)."""
    handoff, carrier = _handoff(env, key)
    brief, _max_chars = _world_brief(key, carrier, research_run_window(handoff), True, monkeypatch)
    snapshot = brief.split("BEGIN UNTRUSTED")[1]
    shown = {row["series"] for row in carrier["series"] if f"\n{data_api().series_label(row)} | " in snapshot}
    for clause in clauses:
        assert shown & clause, (clause, shown)


def test_snapshot_rows_follow_the_question_then_the_carrier(env):
    _handoff_dir, carrier = _handoff(env, "q1_cpi_fed")
    question = QUESTIONS["q1_cpi_fed"]["question"]
    ordered = [row["series"] for row in
               SimulationConfigGenerator._official_data_for_question(carrier, question)["series"]]
    stored = [row["series"] for row in carrier["series"]]
    assert sorted(ordered) == sorted(stored)
    assert ordered[0] in CPI_SERIES and ordered[1] in POLICY_RATE_SERIES  # the named concepts take turns
    unnamed = [series for series in stored if series not in CPI_SERIES | POLICY_RATE_SERIES]
    assert ordered[-len(unnamed):] == unnamed  # core CPI, breakevens, unemployment: carrier order, last
    # Unchanged when the question names none of the series (global sales; US-only series),
    # without a question, or without a carrier.
    _handoff_dir, semis = _handoff(env, "q5_semis")
    assert SimulationConfigGenerator._official_data_for_question(semis, QUESTIONS["q5_semis"]["question"]) is semis
    assert SimulationConfigGenerator._official_data_for_question(carrier, "") is carrier
    assert SimulationConfigGenerator._official_data_for_question(None, question) is None


def test_brief_parts_are_cut_at_lines_then_words():
    part = "## Situation brief\n### Current situation\n" + "Inflation stayed above target for a year. " * 10
    cut = SimulationConfigGenerator._trim_brief_part(part, 200)
    assert len(cut) <= 200 and cut.endswith("…") and cut.startswith("## Situation brief\n### Current situation\n")
    assert part.startswith(cut[:-1] + " ")  # cut at a word boundary, never mid-word
    # Under 60 characters of room only whole lines stay; headings alone are dropped.
    assert SimulationConfigGenerator._trim_brief_part(part, 90) == ""
    assert SimulationConfigGenerator._trim_brief_part("## Hot topics\nA; B", 100) == "## Hot topics\nA; B"
    zh = "## 热点话题\n" + "、".join(f"第{i}个热点话题的具体描述" for i in range(30))
    cut = SimulationConfigGenerator._trim_brief_part(zh, 120)
    assert len(cut) <= 120 and cut.startswith("## 热点话题\n第0个") and cut.endswith("…")


def test_world_brief_without_official_data_is_the_historical_assembly(env, monkeypatch):
    handoff, carrier = _handoff(env, "q1_cpi_fed")
    with_none, max_chars = _world_brief("q1_cpi_fed", None, None, True, monkeypatch)
    assert "UNTRUSTED RESEARCH DATA" not in with_none and len(with_none) == max_chars  # cut as before
    assert SimulationConfigGenerator._fit_official_brief(["q"], ["b"], None, {}, 3000) is None
    assert SimulationConfigGenerator._fit_official_brief(["q"], ["b"], {"schema_version": 1, "series": []},
                                                         {}, 3000) is None


def test_canonical_brief_shares_its_budget_with_the_official_snapshot(env, monkeypatch):
    handoff, carrier = _handoff(env, "q4_ecb_dfr")
    rows = [{"actor_name": f"Actor {i}", "dimension": "knowledge_state", "evidence_type": "verified_fact",
             "claim": f"Public claim {i}: " + "the latest release moved expectations for the policy path. " * 3,
             "source_refs": ["src_web_1"], "as_of_date": "2026-10-01"} for i in range(40)]
    monkeypatch.setattr(SimulationConfigGenerator, "_canonical_public_world_rows",
                        classmethod(lambda cls, actors, packs: deepcopy(rows)))
    brief = SimulationConfigGenerator._build_canonical_public_world_brief(
        QUESTIONS["q4_ecb_dfr"]["question"], {"as_of_date": "2026-10-13"}, {}, 3000, english=True,
        official_data=carrier, official_window=research_run_window(handoff))
    assert len(brief) <= 3000
    assert "## Public, source-bound shared facts\n- Actor 0 / knowledge_state" in brief
    assert brief.count("BEGIN UNTRUSTED RESEARCH DATA") == 1 and "END UNTRUSTED RESEARCH DATA" in brief
    assert "\n\n## Official statistics (published before this world's start date" in brief
    assert "ECB Deposit Facility Rate for Euro Area | 2.375% | 2026-09" in brief


# ------------------------------------------------------------- unchanged without official data


def test_report_prompts_unchanged_without_official_data(env, monkeypatch):
    agent = _agent(monkeypatch, "q1_cpi_fed", None)
    assert agent._data_pack == "" and agent._official_pack_kwargs() == {}
    assert agent._official_outside_view() == ""
    for title in ("Base rates and calibration", "Key official indicators"):
        assert agent._section_official_blocks(title) == []
        assert agent._prepend_research_background("PROMPT", title) == agent._prepend_research_background(
            "PROMPT", "Actors and coalitions")
    model = FakeLLMClient(json_responses=[{"binary_forecasts": []}] * 3)
    fe.extract_binary_forecasts("# Report\n\nBody.", model, min_count=1, horizon_date="2027-12-31")
    prompt = _prompt(model)
    assert "Official data snapshot" not in prompt and "data_anchor" not in prompt
    assert "End of period" not in prompt
