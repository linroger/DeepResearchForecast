"""Deterministic display of stored estimator lanes; never a probability producer."""
from __future__ import annotations

import html

from .forecast_aggregator import pin_aggregation_policy, validate_estimator


def _cell(value):
    return " ".join(html.escape(str(value), quote=False).split()).replace("|", "&#124;").replace("[", "［").replace("]", "］")


def render_estimator_table(forecast, *, chinese=False):
    """Render frozen lanes inside the report's diagnostic fence, without mutation.

    Old reports and the tournament-off authority-only projection keep their
    previous rendering. Missing estimates are explicit rather than zero-filled.
    """
    if not isinstance(forecast, dict) or not forecast.get("estimators"):
        return ""
    rows = [validate_estimator(row) for row in forecast["estimators"]]
    if len(rows) <= 1:
        return ""
    metadata = forecast.get("aggregation") or {}
    policy = pin_aggregation_policy(metadata.get("policy"), authority=(
        "research" if forecast.get("authority") == "target-first-v1" else "spine"))
    labels = {
        "spine": ("报告主预测", "Report spine"), "research": ("研究后验", "Research posterior"),
        "reference_class": ("参考类", "Reference class"), "trend": ("趋势", "Trend"),
        "adversarial": ("反向论证", "Adversarial"), "market_implied": ("市场隐含", "Market implied"),
        "structural": ("结构模型（模拟）", "Structural (simulated)"), "simulation": ("战略模拟", "Strategic simulation"),
    }
    statuses = {"ok": ("可用", "Available"), "unavailable": ("不可用", "Unavailable"), "error": ("失败", "Error")}
    language = 0 if chinese else 1
    title = "估计器对照" if chinese else "Estimator comparison"
    note = ("发布权重为零的估计仅供对照，不改变发布概率。模拟估计不是观测证据；缺失估计显示为“—”。" if chinese else
            "Zero-weight estimates are shown for comparison and do not change published probabilities. Simulated estimates are not observed evidence; missing estimates are shown as —.")
    columns = (["估计器", "状态", "发布权重", "情景估计", "二元命题估计"] if chinese else
               ["Estimator", "Status", "Published weight", "Scenario estimates", "Binary estimates"])
    scenario_names = {str(row.get("id") or row["name"]): row["name"] for row in forecast.get("scenarios", [])}
    lines = ["### " + title, "", note, "", "| " + " | ".join(columns) + " |", "|---|---|---:|---|---|"]
    for row in rows:
        scenarios = "; ".join(f"{scenario_names.get(key, key)}: {value * 100:.10g}%"
                              for key, value in row["scenario_distribution"].items()) or "—"
        binaries = "; ".join(f"{binary['id']}: {binary['p'] * 100:.10g}%" for binary in row["binaries"]) or "—"
        cells = [labels[row["source"]][language], statuses[row["status"]][language],
                 f"{policy['weights'][row['source']]:.10g}", scenarios, binaries]
        lines.append("| " + " | ".join(_cell(value) for value in cells) + " |")
    return "\n".join(lines)
