"""SESSION-B 黄金测试：① 编造溯源修复（source 只可指向确实注入过提示词的模拟信号块）；
② 研究报告情景节 → forecast_inputs 种子的确定性解析（决策通道兜底）及其世界态种子回环。"""

import json

import pytest

from app.services.forecast_extractor import (
    _enforce_source_provenance,
    allowed_signal_labels,
    extract_binary_forecasts,
    reconcile_forecast_contract,
    world_state_outcome_from_signal_pack,
)
from app.utils.actors import (
    forecast_inputs_from_report_markdown,
    world_state_seed_from_actors,
)
from tests.conftest import FakeLLMClient

# ------------------------------------------------------------------ 溯源确定性校验
# 块标记逐字节取自真实渲染器标题行（report_agent._world_state_block / salience_tiers_from_outcomes
# / zep_tools.coalition_map），保证测试与生产信号包格式对齐。
_COALITION_BLOCK = (
    "## 派系/联盟图（按共享互动对象聚类，确定性）\n- 派系 1（3 人）: 甲、乙、丙"
)
_TIERS_BLOCK = (
    "【内部情景推演·议程设置力分层（已确定性转写为定性结论；正文只可引用分层结论，"
    "不得出现任何动作/轮次等机制数字）】\n· 第一梯队（议程主导）：甲、乙"
)
_WORLD_STATE_BLOCK = (
    "【预测结果分布 P(outcome)（内部分析先验；须与外部证据交叉验证）】\n· 突破: 60%\n· 维持现状: 40%"
)


def test_allowed_signal_labels_reflect_injected_blocks():
    labels = allowed_signal_labels(_TIERS_BLOCK + "\n\n" + _COALITION_BLOCK)
    assert labels == {"salience tiers", "coalition map"}
    assert "world-state outcome shares" in allowed_signal_labels(_WORLD_STATE_BLOCK)
    # 空包/None → 空集：任何模拟信号标签都不被允许
    assert allowed_signal_labels("") == set()
    assert allowed_signal_labels(None) == set()


def test_enforce_source_provenance_downgrades_uninjected_and_invented():
    binaries = [
        {"id": "F1", "statement": "a", "probability": 0.6,
         "source": "world-state outcome shares"},        # 未注入 → 编造，降级
        {"id": "F2", "statement": "b", "probability": 0.3,
         "source": "coalition map"},                      # 已注入 → 保留
        {"id": "F3", "statement": "c", "probability": 0.2,
         "source": "research-prior"},                     # 缺省合法值，永远放行
        {"id": "F4", "statement": "d", "probability": 0.7,
         "source": "agent vibe index"},                   # 模型自造名 → 无法对账，降级
        {"id": "F5", "statement": "e", "probability": 0.5,
         "source": "scenario-partition"},                 # 确定性改写值，永远放行
    ]
    n = _enforce_source_provenance(binaries, {"coalition map"})
    assert n == 2
    assert binaries[0]["source"] == "research-prior"
    assert binaries[0]["source_claimed"] == "world-state outcome shares"
    assert binaries[1]["source"] == "coalition map" and "source_claimed" not in binaries[1]
    assert binaries[2]["source"] == "research-prior" and "source_claimed" not in binaries[2]
    assert binaries[3]["source"] == "research-prior"
    assert binaries[3]["source_claimed"] == "agent vibe index"
    assert binaries[4]["source"] == "scenario-partition" and "source_claimed" not in binaries[4]


def _provenance_config(monkeypatch):
    """确定性配置：单轮抽取（contrarian/ensemble 关）、sim 敏感性开（注入 signal_pack）。"""
    from app.config import Config
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_SIM_SENSITIVITY", True, raising=False)
    # Foglamp WP1 (1D)：模拟信号进入二元概率生成仅剩 legacy_prompt（特征化）路径；
    # 本组测试特征化该旧路径的溯源对账/加性行为。
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "legacy_prompt", raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)


def test_extract_binary_forecasts_downgrades_fabricated_signal_source(monkeypatch):
    """取证场景复现：signal_pack 只注入了 coalition 块，模型却声称 world-state 信号
    （world_state_trajectory.json 从未存在过）→ 确定性降级 + 审计计数。"""
    _provenance_config(monkeypatch)
    fake = FakeLLMClient(json_responses=[
        {"binary_forecasts": [
            {"id": "F1", "statement": "Alpha exceeds 10% by 2027", "probability": 0.72,
             "resolution_criteria": "metric > 10% by 2027", "theme": "t1", "horizon_year": 2027,
             "source": "world-state outcome shares"},
            {"id": "F2", "statement": "Beta drops below 500 by 2027", "probability": 0.25,
             "resolution_criteria": "metric < 500 by 2027", "theme": "t2", "horizon_year": 2027,
             "source": "coalition map"},
            {"id": "F3", "statement": "Gamma stays above 3% through 2027", "probability": 0.55,
             "resolution_criteria": "metric > 3% through 2027", "theme": "t3",
             "horizon_year": 2027},
        ]}])
    out = extract_binary_forecasts("dossier", fake, min_count=3, language="English",
                                   signal_pack=_COALITION_BLOCK)
    by_id = {b["id"]: b for b in out["binary_forecasts"]}
    assert by_id["F1"]["source"] == "research-prior"
    assert by_id["F1"]["source_claimed"] == "world-state outcome shares"
    assert by_id["F2"]["source"] == "coalition map" and "source_claimed" not in by_id["F2"]
    assert by_id["F3"]["source"] == "research-prior" and "source_claimed" not in by_id["F3"]
    assert out["binary_quality"]["provenance_downgrades"] == 1
    assert any("simulation signal" in s for s in out["binary_quality"]["issues"])


def test_extract_binary_forecasts_keeps_world_state_label_when_injected(monkeypatch):
    """world-state 块真实注入时，同名 source 标签保留、计数为 0、不加审计 issue。"""
    _provenance_config(monkeypatch)
    fake = FakeLLMClient(json_responses=[
        {"binary_forecasts": [
            {"id": "F1", "statement": "Alpha exceeds 10% by 2027", "probability": 0.72,
             "resolution_criteria": "metric > 10% by 2027", "theme": "t1", "horizon_year": 2027,
             "source": "world-state outcome shares"},
            {"id": "F2", "statement": "Beta drops below 500 by 2027", "probability": 0.25,
             "resolution_criteria": "metric < 500 by 2027", "theme": "t2", "horizon_year": 2027},
        ]}])
    out = extract_binary_forecasts("dossier", fake, min_count=2, language="English",
                                   signal_pack=_WORLD_STATE_BLOCK)
    by_id = {b["id"]: b for b in out["binary_forecasts"]}
    assert by_id["F1"]["source"] == "world-state outcome shares"
    assert "source_claimed" not in by_id["F1"]
    assert out["binary_quality"]["provenance_downgrades"] == 0
    assert not any("simulation signal" in s
                   for s in out["binary_quality"].get("issues", []))


# ------------------------------------------ SIM-3：世界态块标记与渲染器标题同步（漂移守卫）
# 渲染器标题（report_agent._world_state_block 的「【推演结果分布 P(outcome)」）是唯一权威；
# 旧标记只认「【预测结果分布」，legacy_prompt 下引用世界态份额的二元预测被误降级、
# SIM-ADD-3 sim_adjustment 从不触发。下列测试直接对渲染输出断言，渲染器改头即红。
_HOURS_TRAJECTORY = {
    "outcome": {"shares": {"突破": 0.62, "维持现状": 0.38}},
    "converged_at": 4,
    "trajectory": [{"round": 4, "shares": {"突破": 0.62, "维持现状": 0.38}}],
}
_CALENDAR_TRAJECTORY = {
    "outcome": {"shares": {"A": 0.333, "B": 0.333, "C": 0.334}},
    "trajectory": [
        {"round": 1, "shares": {"A": 0.3, "B": 0.4, "C": 0.3}, "period_end": "2026-09-30",
         "label": "2026-Q3"},
        {"round": 2, "shares": {"A": 0.333, "B": 0.333, "C": 0.334},
         "period_end": "2026-12-31", "label": "2026-Q4"},
    ],
    "converged_at": None,
    "schema_version": 3,
    "mode": "calendar",
}


def _rendered_world_state_block(tmp_path, monkeypatch, trajectory, sim_id="sim_ws_marker"):
    from app.config import Config
    from app.services.report_agent import ReportAgent
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path), raising=False)
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "world_state_trajectory.json").write_text(
        json.dumps(trajectory, ensure_ascii=False), encoding="utf-8")
    agent = ReportAgent.__new__(ReportAgent)
    agent.simulation_id = sim_id
    block = agent._world_state_block()
    assert block.startswith("【推演结果分布 P(outcome)")
    return block


def test_world_state_marker_matches_renderer(tmp_path, monkeypatch):
    block = _rendered_world_state_block(tmp_path, monkeypatch, _HOURS_TRAJECTORY)
    assert "world-state outcome shares" in allowed_signal_labels(block)
    out = world_state_outcome_from_signal_pack(block)
    assert out == {"scenario_shares": {"突破": 0.62, "维持现状": 0.38},
                   "converged": True, "source": "world-state outcome shares"}


def test_world_state_marker_matches_calendar_renderer(tmp_path, monkeypatch):
    """日历（v3）渲染：份额行后接演化航点——解析只取份额行并归一（33%×3 → 各 1/3）。"""
    block = _rendered_world_state_block(tmp_path, monkeypatch, _CALENDAR_TRAJECTORY)
    assert "world-state outcome shares" in allowed_signal_labels(block)
    out = world_state_outcome_from_signal_pack(block)
    assert out["scenario_shares"] == {"C": 0.3333, "A": 0.3333, "B": 0.3333}
    assert out["converged"] is False


def _extract_and_reconcile(block):
    """extract_binary_forecasts on ``block`` (F1 cites the world-state shares), then the
    report_agent call order: binary_quality is attached to the forecast before
    reconcile_forecast_contract, which records SIM-ADD-3 sim_adjustment from it."""
    fake = FakeLLMClient(json_responses=[
        {"binary_forecasts": [
            {"id": "F1", "statement": "Alpha exceeds 10% by 2027", "probability": 0.72,
             "resolution_criteria": "metric > 10% by 2027", "theme": "t1", "horizon_year": 2027,
             "source": "world-state outcome shares"},
            {"id": "F2", "statement": "Beta drops below 500 by 2027", "probability": 0.25,
             "resolution_criteria": "metric < 500 by 2027", "theme": "t2", "horizon_year": 2027},
        ]}])
    out = extract_binary_forecasts("dossier", fake, min_count=2, language="English",
                                   signal_pack=block)
    forecast = {
        "scenarios": [{"name": "突破", "probability": 0.5},
                      {"name": "维持现状", "probability": 0.5}],
        "binary_forecasts": out["binary_forecasts"],
        "binary_quality": out["binary_quality"],
    }
    reconcile_forecast_contract(forecast)
    return {b["id"]: b for b in out["binary_forecasts"]}, out["binary_quality"], forecast


def _assert_world_state_downgraded(by_id, bq, forecast):
    assert by_id["F1"]["source"] == "research-prior"
    assert by_id["F1"]["source_claimed"] == "world-state outcome shares"
    assert bq["provenance_downgrades"] == 1
    assert "world_state_outcome" not in bq
    assert "sim_adjustment" not in forecast


@pytest.mark.parametrize("effect, kept", [("legacy_prompt", True), ("diagnostic_only", False)])
def test_rendered_world_state_block_reaches_provenance_and_sim_adjustment(
        tmp_path, monkeypatch, effect, kept):
    """legacy_prompt：渲染块真实注入 → 引用世界态份额的 source 保留、world_state_outcome 落
    binary_quality，reconcile_forecast_contract 据此记下 SIM-ADD-3 sim_adjustment。
    默认 diagnostic_only：允许集只在 sim_sensitive 时计算，行为不变（照旧降级、不落
    world_state_outcome、无 sim_adjustment）。"""
    block = _rendered_world_state_block(tmp_path, monkeypatch, _HOURS_TRAJECTORY)
    _provenance_config(monkeypatch)
    from app.config import Config
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", effect, raising=False)
    by_id, bq, forecast = _extract_and_reconcile(block)
    if kept:
        assert by_id["F1"]["source"] == "world-state outcome shares"
        assert "source_claimed" not in by_id["F1"]
        assert bq["provenance_downgrades"] == 0
        assert bq["world_state_outcome"]["scenario_shares"] == {"突破": 0.62, "维持现状": 0.38}
        adj = forecast["sim_adjustment"]
        assert adj["scenario_shares"] == {"突破": 0.62, "维持现状": 0.38}
        assert adj["delta_vs_research_prior"] == {"突破": 0.12, "维持现状": -0.12}
        assert adj["converged"] is True
    else:
        _assert_world_state_downgraded(by_id, bq, forecast)


@pytest.mark.parametrize("hide", [True, False])
def test_non_valid_world_state_block_is_not_a_citable_signal(tmp_path, monkeypatch, hide):
    """显式非 valid 裁定（「本分布不可用作任何依据」）的渲染块：legacy_prompt 下既不进允许集
    （引用它的二元预测照旧降级），也不被解析成 world_state_outcome / sim_adjustment——
    REPORT_WORLDSTATE_HIDE_INVALID 关闭时块内仍列份额，同样 fail-closed。"""
    from app.config import Config
    monkeypatch.setattr(Config, "REPORT_WORLDSTATE_HIDE_INVALID", hide, raising=False)
    trajectory = dict(_HOURS_TRAJECTORY, validity="inconclusive",
                      validity_reasons=["failed_rounds"])
    block = _rendered_world_state_block(tmp_path, monkeypatch, trajectory)
    assert "⚠️ 有效性裁定：inconclusive" in block
    assert ("· 突破: 62%" in block) is not hide     # knob off: the shares are still listed
    assert "world-state outcome shares" not in allowed_signal_labels(block)
    assert world_state_outcome_from_signal_pack(block) is None
    _provenance_config(monkeypatch)
    _assert_world_state_downgraded(*_extract_and_reconcile(block))


@pytest.mark.parametrize("pack, usable", [
    # a verdict line that says valid does not block the block
    ("【推演结果分布 P(outcome)】\n⚠️ 有效性裁定：valid\n· A: 60%\n· B: 40%", True),
    # an unreadable verdict fails closed
    ("【推演结果分布 P(outcome)】\n⚠️ 有效性裁定：\n· A: 60%\n· B: 40%", False),
    # the verdict check stays inside the world-state block: text in a later block is ignored
    ("【推演结果分布 P(outcome)】\n· A: 60%\n· B: 40%\n\n## 派系/联盟图\n有效性裁定：invalid", True),
    ("【推演结果分布 P(outcome)】\n· A: 60%\n· B: 40%\n\n【因果骨架】\n有效性裁定：invalid", True),
])
def test_world_state_verdict_check_is_scoped_to_its_block(pack, usable):
    assert ("world-state outcome shares" in allowed_signal_labels(pack)) is usable
    out = world_state_outcome_from_signal_pack(pack)
    assert (out is not None) is usable
    if usable:
        assert out["scenario_shares"] == {"A": 0.6, "B": 0.4}


# ------------------------------------------ 研究报告情景节 → forecast_inputs 种子解析
# 英文样例：从真实研究报告 pipe_750d99882585/handoff/research_report.md
# 「## Four Mutually Exclusive Scenarios」节逐字截取（正文缩减）。
EN_SCENARIO_MD = """\
# Humanoid Robotics Deep Research

## Four Mutually Exclusive Scenarios

The scenarios below are weighted to sum to 100% and represent forecasts for 2030 global humanoid annual shipments.

### Scenario A: Base Case — "Structured Scale" (45% probability)

**Description**: Humanoids achieve commercial scale in structured manufacturing and intra-logistics. Consumer/home-help remains negligible (<5% of fleet value).

**Key assumptions**:
- Actuator learning curves deliver 30–40% BOM reduction by 2030
- Tesla achieves 50,000–80,000 Optimus production (predominantly internal use)

### Scenario B: Upside Case — "General-Purpose Acceleration" (25% probability)

**Description**: VLA model breakthroughs enable reliable generalization across tasks. Annual global shipments reach 100,000–200,000 units by 2030.

### Scenario C: Missed Case — "Pilot Plateau" (20% probability)

**Description**: Humanoids remain stuck at pilot scale. Annual global shipments plateau at 10,000–25,000 units by 2030.

### Scenario D: Downside Case — "AI Winter for Embodied AI" (10% probability)

**Description**: The category faces a credibility collapse. Annual shipments stay below 10,000 units by 2030.

## Quantitative Forecast Table
"""

ZH_SCENARIO_MD = """\
# 全球电动车渗透率深度研究

## 情景概率分布

基于参照类分析与当前证据，给出如下互斥情景分布：

- **基准情景（概率 0.55）**：中国维持全球主导地位，渗透率稳步提升至 52%。
- **政策推动情景（15%）**：欧盟严格执行 2035 禁燃令，美国恢复购置补贴。
- **停滞情景（概率 0.2）**：需求进入平台期，全球份额停在 25-30% 的水平。
- **加速情景（10–15%）**：油价长期高于 120 美元/桶，中国出口扩张提速。

## 关键驱动变量
"""

# 英文样例：来自网格储能恢复运行 pipe_0e1b84d2682a 的实际全局合成格式。
# 节标题里的 100% 是总和约束，不是单个情景概率；旧解析器因此跳过整节。
AGGREGATE_TOTAL_SCENARIO_MD = """\
# Grid-scale Energy Storage Forecast

## Scenarios (4 mutually exclusive, summing to 100%)

### SCN-A — Lithium Dominance: 30%

High-scale, low-diversification outcome.

### SCN-B — LDES Diversified: 25%

High-scale, high-diversification outcome.

### SCN-C — China-Centric Vertical: 20%

Lower global growth with a China-centric supply chain.

### SCN-D — Stagnation: 25%

Deployment decelerates because constraints remain non-technological.

## Binary Forecasts
"""


def test_parse_english_heading_style_scenario_section():
    parsed = forecast_inputs_from_report_markdown(EN_SCENARIO_MD)
    assert set(parsed) == {"scenarios", "base_rates"}
    assert parsed["base_rates"] == []
    rows = parsed["scenarios"]
    assert [r["name"] for r in rows] == [
        'Scenario A: Base Case — "Structured Scale"',
        'Scenario B: Upside Case — "General-Purpose Acceleration"',
        'Scenario C: Missed Case — "Pilot Plateau"',
        'Scenario D: Downside Case — "AI Winter for Embodied AI"',
    ]
    assert [r["probability"] for r in rows] == [0.45, 0.25, 0.20, 0.10]
    # 正文里的 "30–40%" / "<5%" 等无关百分数绝不产生幽灵情景
    assert len(rows) == 4


def test_parse_chinese_bold_list_scenario_section():
    parsed = forecast_inputs_from_report_markdown(ZH_SCENARIO_MD)
    rows = parsed["scenarios"]
    assert [r["name"] for r in rows] == ["基准情景", "政策推动情景", "停滞情景", "加速情景"]
    assert rows[0]["probability"] == 0.55          # "概率 0.55" 小数型
    assert rows[1]["probability"] == 0.15          # "(15%)" 单点百分数
    assert rows[2]["probability"] == 0.2
    assert rows[3]["probability_band"] == "10–15%"  # 区间保留原文
    assert "probability" not in rows[3]


def test_parse_section_heading_with_aggregate_100_percent_invariant():
    parsed = forecast_inputs_from_report_markdown(AGGREGATE_TOTAL_SCENARIO_MD)
    rows = parsed["scenarios"]
    assert [r["name"] for r in rows] == [
        "SCN-A — Lithium Dominance",
        "SCN-B — LDES Diversified",
        "SCN-C — China-Centric Vertical",
        "SCN-D — Stagnation",
    ]
    assert [r["probability"] for r in rows] == [0.30, 0.25, 0.20, 0.25]


def test_parse_rejects_missing_probabilities_and_thin_sections():
    no_prob = (
        "## Scenarios\n\n"
        "### Scenario A: Base Case\n\nProse without any probability.\n\n"
        "### Scenario B: Upside Case\n\nMore prose.\n"
    )
    assert forecast_inputs_from_report_markdown(no_prob) == {}
    single = "## 情景概率分布\n\n- **唯一情景（概率 0.95）**：只有一个情景不构成分布。\n"
    assert forecast_inputs_from_report_markdown(single) == {}
    assert forecast_inputs_from_report_markdown("") == {}
    assert forecast_inputs_from_report_markdown("no scenario section at all") == {}


def test_parse_rejects_probabilities_not_summing_near_one():
    bad_sum = (
        "## Scenario Probability Distribution\n\n"
        "- **Alpha Scenario (30% probability):** first outcome.\n"
        "- **Beta Scenario (30% probability):** second outcome.\n"
    )
    assert forecast_inputs_from_report_markdown(bad_sum) == {}   # 0.6 ∉ [0.9, 1.1]
    over_sum = (
        "## Scenario Probability Distribution\n\n"
        "- **Alpha Scenario (80% probability):** first outcome.\n"
        "- **Beta Scenario (60% probability):** second outcome.\n"
    )
    assert forecast_inputs_from_report_markdown(over_sum) == {}  # 1.4 ∉ [0.9, 1.1]


def test_round_trip_parsed_scenarios_seed_world_state():
    """回环：报告解析出的 forecast_inputs 直接喂 world_state_seed_from_actors，
    须得到非空情景集 + 非空基率（决策通道种子由此点火，而非静默 50/50）。"""
    parsed = forecast_inputs_from_report_markdown(EN_SCENARIO_MD)
    seed = world_state_seed_from_actors({"forecast_inputs": parsed})
    assert len(seed["scenarios"]) == 4
    assert len(seed["base_rates"]) == 4
    assert abs(sum(seed["base_rates"].values()) - 1.0) < 0.02
    assert seed["uniform_prior"] is False
    # 中文粗体列表版式同样成种（含区间中点 0.125）
    zh_seed = world_state_seed_from_actors(
        {"forecast_inputs": forecast_inputs_from_report_markdown(ZH_SCENARIO_MD)})
    assert zh_seed["base_rates"]["加速情景"] == 0.125
    assert zh_seed["uniform_prior"] is False
