"""2026-10-22 SIM-RECONCILE: 模拟→报告有界影响 + 世界变量现实主义阻尼。

三组防线（sim_3ec25e64209e 复盘——无人机发射强度 9 日 -38%）：
  * ``set_value`` 软回归（κ 向研究锚点）+ 硬累计漂移上限（±35%）；
  * pending effect 落地路径补上同样的钳制（此前完全绕过，单轮 -46%）；
  * 理由明示未来日期的变更/效应不当轮生效，按时间线转 pending。
以及骨架侧：模拟份额基准分布锚点（band/advisory）、判定日单一权威、
spine block 的「模拟对照」行。
"""

import math
from types import SimpleNamespace

from app.services.forecast_extractor import (
    derive_forecast_spine,
    render_forecast_spine_block,
)
from app.services.world_model import (
    DEFAULT_MAX_DRIFT_RATIO,
    DEFAULT_REVERSION_KAPPA,
    WorldModel,
    _earliest_future_date,
)


# ---------------------------------------------------------------------------
# world realism damping
# ---------------------------------------------------------------------------

def _world_with_drone(value=337.0, period=None):
    w = WorldModel(question="q", as_of_date="2026-10-22")
    w.add_variable("Drone launch tempo", value, unit="count", kind="numeric",
                   as_of="2026-10-18", provenance="research", var_id="drone_launch_tempo")
    if period:
        w.period = period
    return w


def test_set_value_reversion_pulls_toward_research_anchor():
    w = _world_with_drone()
    var = w.variables["drone_launch_tempo"]
    # 仲裁一步 337→180（-46.6%）：三道防线叠加——步长钳 0.5（不触界）→ 回归 κ=0.15
    # 拉到 203.55 → 漂移下限 337×0.65=219.05 兜底截断；最终停在硬下限。
    var.set_value(180.0, round_num=1, source="arbiter", cause="talks soon",
                  max_change_ratio=0.5, reversion_kappa=DEFAULT_REVERSION_KAPPA,
                  max_drift_ratio=DEFAULT_MAX_DRIFT_RATIO)
    assert math.isclose(float(var.value), 337.0 * 0.65, rel_tol=1e-9)
    cause = var.history[-1]["cause"]
    assert "damped" in cause and "回归锚点" in cause and "累计漂移" in cause


def test_set_value_drift_cap_bounds_cumulative_excursion():
    w = _world_with_drone()
    var = w.variables["drone_launch_tempo"]
    # 无回归（κ=0）时硬上限单独生效：337×(1-0.35)=219.05
    var.set_value(50.0, round_num=1, source="arbiter", cause="crash",
                  max_change_ratio=0.5, reversion_kappa=0.0,
                  max_drift_ratio=DEFAULT_MAX_DRIFT_RATIO)
    assert math.isclose(float(var.value), 337.0 * 0.65, rel_tol=1e-9)
    assert "累计漂移" in var.history[-1]["cause"]


def test_monotone_anticipation_drift_converges_short_of_uncapped():
    """每日 -8% 的同向小步（"会谈前适度降温"）在回归+漂移上限下远离无阻尼轨迹。"""
    w = _world_with_drone()
    var = w.variables["drone_launch_tempo"]
    cur = 337.0
    uncapped = cur
    for rnd in range(1, 10):
        target = float(var.value) * 0.92
        var.set_value(target, round_num=rnd, source="arbiter", cause="pre-talks moderation",
                      max_change_ratio=0.5, reversion_kappa=DEFAULT_REVERSION_KAPPA,
                      max_drift_ratio=DEFAULT_MAX_DRIFT_RATIO)
        uncapped *= 0.92
    assert float(var.value) > uncapped              # 阻尼强于无阻尼复合
    assert float(var.value) >= 337.0 * 0.65 - 1e-6  # 且永不破硬下限


def test_seed_path_unchanged_without_damping_kwargs():
    w = _world_with_drone()
    var = w.variables["drone_launch_tempo"]
    var.set_value(999.0, round_num=1, source="research", cause="re-anchored")
    assert float(var.value) == 999.0
    assert "damped" not in var.history[-1]["cause"]


def test_future_dated_change_deferred_to_pending():
    period = {"period_start": "2026-10-25", "period_end": "2026-10-25", "label": "2026-10-25"}
    w = _world_with_drone(period=period)
    w.round = 3
    update = {"variable_changes": [
        {"variable_id": "drone_launch_tempo", "new_value": 180.0,
         "rationale": "Trilateral talks begin ~Nov 10–17; energy ceasefire likely first step"},
    ]}
    summary = w.apply_arbiter_update(3, update)
    # 不当轮生效：值不变，转 pending，到期轮按日粒度推到 11 月之后
    assert float(w.variables["drone_launch_tempo"].value) == 337.0
    assert summary["deferred_changes"], summary
    assert summary["deferred_changes"][0]["cites_date"].startswith("2026-11")
    assert w.pending_effects and w.pending_effects[0].due_round > 3
    assert not summary["variables_changed"]


def test_present_dated_change_applies_immediately():
    period = {"period_start": "2026-10-25", "period_end": "2026-10-25", "label": "2026-10-25"}
    w = _world_with_drone(period=period)
    update = {"variable_changes": [
        {"variable_id": "drone_launch_tempo", "delta": -18.0,
         "rationale": "Strike pause announced 2026-10-24; tempo eases"},
    ]}
    summary = w.apply_arbiter_update(1, update)
    assert summary["variables_changed"], summary
    assert not summary["deferred_changes"]
    assert float(w.variables["drone_launch_tempo"].value) < 337.0


def test_effect_path_now_clamped():
    """fire_due_effects 此前绕过一切钳制（sim_3ec25e64209e r3 单轮 -46%）。"""
    from app.services.world_model import PendingEffect
    w = _world_with_drone()
    w.pending_effects.append(PendingEffect(
        "fx1", due_round=1, description="sudden collapse",
        variable_id="drone_launch_tempo", op="set", value=100.0,
        probability=1.0, source="arbiter", created_round=0))
    fired = w.fire_due_effects(1, rng=SimpleNamespace(random=lambda: 0.0))
    assert fired and fired[0]["variable_ids"]
    val = float(w.variables["drone_launch_tempo"].value)
    # 步长钳（≤-50%）+ 回归 + 漂移下限三重之后，绝不该是裸 100
    assert val > 100.0
    assert val >= 337.0 * 0.65 - 1e-6
    assert "damped" in w.variables["drone_launch_tempo"].history[-1]["cause"]


def test_earliest_future_date_yearless_rolls_forward():
    d = _earliest_future_date("talks begin ~Nov 10–17", "2026-10-25")
    assert d is not None and d.isoformat() == "2026-11-10"
    # 引用过去日期（as_of 标注）不当未来事件
    assert _earliest_future_date("level as of 2026-10-18 per ISW", "2026-10-25") is None


# ---------------------------------------------------------------------------
# spine: simulation anchor + horizon authority
# ---------------------------------------------------------------------------

class _SpineLLM:
    """返回固定骨架 JSON；记录收到的提示词供断言。"""

    def __init__(self, horizon="2028-12-31"):
        self.horizon = horizon
        self.seen = []

    def chat_json(self, messages, temperature=0.2, max_tokens=None):
        self.seen.append(messages[-1]["content"])
        return {
            "headline": "h", "horizon": self.horizon, "confidence": "medium",
            "scenarios": [
                {"name": "Stalemate with fragile talks", "probability": 0.4,
                 "summary": "s", "key_drivers": ["d"],
                 "base_rate_anchor": "b", "adjustment_rationale": "a",
                 "resolution_criteria": "c"},
                {"name": "Ukraine ceasefire, Iran holds", "probability": 0.3,
                 "summary": "s", "key_drivers": ["d"],
                 "base_rate_anchor": "b", "adjustment_rationale": "a",
                 "resolution_criteria": "c"},
            ],
            "key_uncertainties": ["u"], "confidence_rationale": "r",
        }


_SHARES = {"Stalemate with fragile talks": 0.51276, "Ukraine ceasefire, Iran holds": 0.29229,
           "Dual de-escalation": 0.131866}


def test_spine_anchor_band_mode_text_and_echo():
    llm = _SpineLLM()
    out = derive_forecast_spine(
        llm, central_question="q", horizon="2027-10-22",
        base_distribution=dict(_SHARES), anchor_mode="band",
        anchor_meta={"sim_horizon": "2027-10-22", "coverage": 1.0, "mode": "band"})
    assert "基准分布锚点" in llm.seen[0] and "合理带内" in llm.seen[0]
    assert out["simulation_anchor"]["mode"] == "band"
    assert out["simulation_anchor"]["sim_horizon"] == "2027-10-22"
    assert out["base_distribution"]["Stalemate with fragile talks"] > 0.5
    # R2-CAL-18：0.40 vs 0.51 分歧 <0.2 → 无强制降信心，但对照数据在场
    assert all(isinstance(s.get("worldstate_divergence"), float) for s in out["scenarios"])


def test_spine_anchor_advisory_mode_keeps_research_authority():
    llm = _SpineLLM()
    out = derive_forecast_spine(
        llm, central_question="q", horizon="2026-10-31",
        base_distribution=dict(_SHARES), anchor_mode="advisory",
        anchor_meta={"sim_horizon": "2026-10-31", "coverage": 0.03, "mode": "advisory"})
    assert "机制先验" in llm.seen[0] and "非终端分布" in llm.seen[0]
    assert "合理带内" not in llm.seen[0]
    assert out["simulation_anchor"]["mode"] == "advisory"


def test_render_spine_block_includes_simulation_reconciliation():
    fc = {
        "headline": "h", "horizon": "2027-10-22", "confidence": "medium",
        "scenarios": [
            {"name": "Stalemate with fragile talks", "probability": 0.45},
            {"name": "Ukraine ceasefire, Iran holds", "probability": 0.25},
        ],
        "base_distribution": dict(_SHARES),
        "simulation_anchor": {"mode": "band", "sim_horizon": "2027-10-22"},
    }
    block = render_forecast_spine_block(fc)
    assert "模拟对照" in block
    assert "45%" in block and "51%" in block  # 骨架概率与模拟份额并列可见
    # 无锚点的骨架逐字节保持旧格式（不含对照段）
    old = render_forecast_spine_block({k: v for k, v in fc.items()
                                       if k not in ("base_distribution", "simulation_anchor")})
    assert "模拟对照" not in old
