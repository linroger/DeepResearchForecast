"""Single source of truth for how simulation output is named and labelled.

Simulation output is a ``simulated`` record class: never evidence, never a
probability input (ADR 0003; invariant I-11).  Every reader-facing string that
identifies it — chart titles, the executive-brief disclosure, the lint
whitelist, the dashboard badge and (slice S3) the report bridge title and
banner — imports from here, so a renamed label cannot silently diverge from
the lint that recognises it.  The ``【预测结果分布`` / ``【推演结果分布`` header
drift between ``report_agent`` and ``forecast_extractor`` is the precedent
this module exists to prevent.

Design: docs/handoff/simulation-after-action-record/design.md §3.5.
Tests:  backend/tests/test_sim_provenance_constants.py (T9).

Rules for editing this module:

* A string here is a contract.  Changing it requires updating every consumer
  listed in T9 and, for the dashboard strings, the Vue i18n call sites that
  the test reads back.
* Do not add laundering labels.  A label that presents simulation output as
  analysis, evidence, a panel view or an attributed viewpoint ("scenario
  panel", "analytical perspective", "evidence-based assessment") is exactly
  what ADR 0003 removes.
"""
from __future__ import annotations

import re
from typing import Final

# ── Record identity ──────────────────────────────────────────────────────────
RECORD_SCHEMA: Final = "simulation-record/v1"
RECORD_CLASS: Final = "simulated"
EPISTEMIC_STATUS: Final = "elicited_model_projection"

# ── The one reader-facing name ───────────────────────────────────────────────
SIM_LABEL_EN: Final = "scenario simulation"
SIM_LABEL_ZH: Final = "情景模拟"

# ── Dashboard badge and caveat (pinned to the Vue i18n call sites by T9) ─────
# WorldStatePanel.vue renders the badge on every committed round;
# WorldSimulationView.vue renders the caveat above the world-v1 result.
SIM_BADGE_EN: Final = "model projection, not evidence"
SIM_BADGE_ZH: Final = "推演投影，非观察证据"
SIM_CAVEAT_EN: Final = (
    "Conditional pathway under declared assumptions; not a calibrated probability forecast."
)
SIM_CAVEAT_ZH: Final = "声明假设下的条件路径；不是经过校准的概率预测。"

# ── Banner carried by the record and the report bridge ───────────────────────
SIM_BANNER_EN: Final = (
    "Simulated under declared assumptions. Not observed facts, not a calibrated "
    "probability, and not an input to any probability in this report."
)
SIM_BANNER_ZH: Final = "声明假设下的模拟；非观察事实，非校准概率，未作为本报告任何概率的输入。"

# ── Report bridge section (rendered by slice S3; constants fixed now) ─────────
BRIDGE_TITLE_EN: Final = "Scenario simulation: what the exercise explored"
BRIDGE_TITLE_ZH: Final = "情景模拟：推演探索了什么"
BRIDGE_START: Final = "<!-- sim-bridge:start -->"
BRIDGE_END: Final = "<!-- sim-bridge:end -->"

# ── Simulated charts ─────────────────────────────────────────────────────────
# Every chart drawn from simulation artifacts carries "Simulated" in its title
# and the placement hint ``simulation``, so the executive brief can never pick
# one as the report's load-bearing chart and the report never files one under
# the evidence-based scenario section.
CHART_PLACEMENT_HINT: Final = "simulation"
CHART_OUTCOME_SHARES_EN: Final = "Simulated outcome-share trajectory"
CHART_OUTCOME_SHARES_ZH: Final = "模拟结果份额轨迹"
CHART_WORLD_VARIABLES_EN: Final = "Simulated World Variables (indexed, seed = 100)"
CHART_WORLD_VARIABLES_ZH: Final = "推演世界变量（指数化，种子值 = 100）"
SIMULATED_CHART_IDS: Final = frozenset({"worldstate_trajectory", "world_variables"})
SIMULATED_CHART_TITLES_EN: Final = frozenset({CHART_OUTCOME_SHARES_EN, CHART_WORLD_VARIABLES_EN})

# ── Scenario-share block header (report_agent renders, forecast_extractor parses) ──
OUTCOME_SHARES_HEADER_ZH: Final = "推演结果分布 P(outcome)"
# Pre-2026-10 renderer wording, still present in legacy_prompt fixtures.  Only
# the extractor's reader accepts it; nothing renders it any more.
OUTCOME_SHARES_HEADER_LEGACY_ZH: Final = "预测结果分布 P(outcome)"

# ── Honest quotation labels ──────────────────────────────────────────────────
# A blockquote carrying one of these words is recognised as simulation output
# by the quote-grounding audit (it is not a fabricated *real* quotation).  It is
# still simulation content and is removed from report prose by the leakage
# lint; the label only decides which defect it is counted as.  Panel/viewpoint
# wording is deliberately absent (see module docstring).
SIM_QUOTE_LABELS: Final = (
    "模拟", "simulation", "代理人", "推演", "sim-agent", "simulated agent",
    SIM_LABEL_EN, SIM_LABEL_ZH,
)

# ── Executive brief disclosure line ──────────────────────────────────────────
# ``{health}`` is run_summary's simulation_health; ``{detail}`` is the organic
# action count fragment (may be empty).
BRIEF_SIM_LINE_EN: Final = (
    "scenario simulation ran ({health}{detail}); informed mechanism analysis only, "
    "never probabilities (policy: diagnostic_only)"
)
BRIEF_SIM_LINE_ZH: Final = (
    "情景模拟已运行（{health}{detail}）；仅用于机制分析，从不进入概率（策略：diagnostic_only）"
)


def outcome_shares_header_re() -> "re.Pattern[str]":
    """Regex matching the scenario-share block header the report renders
    (``【推演结果分布 P(outcome)``), plus the pre-2026-10 wording kept only so
    legacy_prompt fixtures still parse.  Shared by ``forecast_extractor``."""
    stems = sorted({h.split(" P(")[0] for h in (OUTCOME_SHARES_HEADER_ZH, OUTCOME_SHARES_HEADER_LEGACY_ZH)})
    return re.compile("【(?:" + "|".join(re.escape(x) for x in stems) + r")\s*P\(outcome\)")


def chart_title(chart_id: str, lang: str = "en") -> str:
    """Title of a simulated chart by visualizer id; raises for a non-simulated id."""
    zh = str(lang or "").lower().startswith("zh")
    if chart_id == "worldstate_trajectory":
        return CHART_OUTCOME_SHARES_ZH if zh else CHART_OUTCOME_SHARES_EN
    if chart_id == "world_variables":
        return CHART_WORLD_VARIABLES_ZH if zh else CHART_WORLD_VARIABLES_EN
    raise KeyError(f"not a simulated chart id: {chart_id!r}")


def is_simulated_chart(item: object) -> bool:
    """True for a viz-manifest entry that was drawn from simulation artifacts.

    Checks the id, the placement hint and the title, so a stale manifest written
    by an older visualizer is still recognised.
    """
    if not isinstance(item, dict):
        return False
    if str(item.get("id") or "") in SIMULATED_CHART_IDS:
        return True
    if str(item.get("placement_hint") or "") == CHART_PLACEMENT_HINT:
        return True
    title = str(item.get("title") or item.get("caption") or "")
    return title in SIMULATED_CHART_TITLES_EN or title in {
        CHART_OUTCOME_SHARES_ZH, CHART_WORLD_VARIABLES_ZH, "Forecast Outcome-Share Trajectory",
    }
